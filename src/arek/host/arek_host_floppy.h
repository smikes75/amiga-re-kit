/* arek_host_floppy.h - drive DF0 and Paula's disk controller for a host whose game reads the disk with its OWN loader
 * (-DHOST_FLOPPY=1; kit 1.0.53, SWIV). The read routine is then translated like the rest of the game - no extern, no
 * measured table of read times: the bytes pass under the head at the speed of the disk, the controller waits for the
 * sync word, its words go to DSKPT in the disk's DMA slots and DSKBLK is raised when DSKLEN has run out.
 *
 * After the model of vAmiga (DiskController, FloppyDrive, AmigaEncoder; the reference the kit measures against):
 *   - the track: 11 AmigaDOS sectors of 1088 MFM bytes from the ADF (4 x $AA, $4489 $4489, info, 32 x $AA, the two
 *     checksums, the data odd / even) and $AA up to 12 668 bytes; one byte every 60 s / 300 / 12 668 (442.06 master
 *     cycles = 55.26 colour clocks) while the drive is selected and its motor is on;
 *   - the controller: the bits shift through DSKDATR's register, a byte goes to a FIFO of 3 words; a match with
 *     DSKSYNC raises DSKSYN and, with ADKCON WORDSYNC, starts the read (WAIT -> READ); the second of two writes of
 *     DSKLEN with DMAEN starts it; in each of the line's three disk slots ($07, $09, $0B) one word leaves the FIFO for
 *     (DSKPT)+ when DMACON has DSKEN and DMAEN; the last word raises DSKBLK and ends the read;
 *   - the drive: CIA-B PRB /MTR (latched at the falling edge of /SEL0), /SEL0, /SIDE, DIR, /STEP (a rising edge while
 *     selected); CIA-A PRA /RDY (low at full speed: 380 ms after the motor was switched on), /TK0, /WPRO (high),
 *     /CHNG; a step holds the head for 12 ms (the bytes read as 0 meanwhile).
 * Reading only: a write to the disk is refused (the controller stays off). DF0 only. The image is AHD_IMG[0]
 * (arek_host_disk.h: engine_set_disk / ahd_set_file).
 *
 * The bus: a transferred word takes its slot from the CPU. The host runs the model up to the CPU's time at every
 * instruction and marks the slots of the next colour clocks from a copy run ahead (a CPU access inside the
 * instruction then waits as the original's does).
 *
 * What a state does not carry starts from defaults the project sets before the run: host_floppy_start(cylinder,
 * byte under the head, colour clocks to the next byte). Needs before it: the translation, arek_host_disk.h and the
 * host's time (h_abs), INTREQ and CIA helpers - arek_host.h includes it. Header-only, MIT. No game data. */
#ifndef AREK_HOST_FLOPPY_H
#define AREK_HOST_FLOPPY_H

#define HFL_TRACK 12668
#define HFL_BYTE_M 442.05873065992264            /* master cycles a byte: 28 000 000 * 60 / 300 / 12 668 */
#define HFL_START_CCK (380.0 * 28000.0 / 8.0)    /* the motor to full speed */
#define HFL_STOP_CCK (80.0 * 28000.0 / 8.0)
#define HFL_STEP_GAP_CCK (40.0 * 28.0 / 8.0)     /* two step pulses closer than this are one */
#define HFL_SETTLE_CCK (12.0 * 28000.0 / 8.0)    /* track to track + head settle */
#define AREK_BUS_DISK 3

typedef struct {
    int cyl, side, motor, dskchange; double sw_t, sw_speed, step_done, last_step; long off; uint8_t prb;
    int state; uint16_t dsklen, dsksync, datareg, incoming, adkcon, dmacon; int dregcnt, fifocnt; uint64_t fifo; uint32_t dskpt;
    double sync_t, acc, dma_done; long long next_m;
    int tcyl, tside, tvalid; uint8_t trk[HFL_TRACK];
    long words, syncs, bytes;
} HFloppy;
static HFloppy HFL;

static void hfl_reset(void) {
    memset(&HFL, 0, sizeof HFL);
    HFL.prb = 0xff; HFL.dsksync = 0x4489; HFL.dskchange = 1; HFL.step_done = -1e30; HFL.last_step = -1e30; HFL.sw_t = -1e30;
    HFL.sync_t = -1e30; HFL.dma_done = -1e30; HFL.next_m = -1;
}
/* the project's start: the head's cylinder, the byte of the track under it, colour clocks from the start to the next byte */
static void host_floppy_start(int cyl, long off, double to_next_byte) {
    HFL.cyl = cyl; HFL.off = ((off % HFL_TRACK) + HFL_TRACK) % HFL_TRACK; HFL.tvalid = 0;
    HFL.next_m = (long long)floor((h_abs() + to_next_byte) * 8.0 + 0.5); HFL.acc = 0;
}

/* ---- the track as the head reads it (vAmiga AmigaEncoder) ---- */
static void hfl_oddeven(uint8_t *dst, const uint8_t *src, int n) {
    for (int i = 0; i < n; i++) dst[i] = (uint8_t)((src[i] >> 1) & 0x55);
    for (int i = 0; i < n; i++) dst[i + n] = (uint8_t)(src[i] & 0x55);
}
static uint8_t hfl_clock(uint8_t v, uint8_t prev) {
    v &= 0x55; uint8_t inv = (uint8_t)((uint8_t)(v << 1) | (uint8_t)(v >> 1 | prev << 7));
    return (uint8_t)(v | (inv ^ 0xaa));
}
static int hfl_bit(const uint8_t *t, long bit) { bit = ((bit % (8L * HFL_TRACK)) + 8L * HFL_TRACK) % (8L * HFL_TRACK); return (t[bit >> 3] >> (7 - (bit & 7))) & 1; }
static void hfl_encode(int cyl, int side) {
    uint8_t *t = HFL.trk; int track = cyl * 2 + side;
    memset(t, 0xaa, HFL_TRACK);
    long base = (long)track * 11 * 512;
    for (int s = 0; s < 11; s++) {
        uint8_t *it = t + s * 1088, data[512], info[4] = { 0xff, (uint8_t)track, (uint8_t)s, (uint8_t)(11 - s) }, bc[4] = { 0, 0, 0, 0 }, dc[4] = { 0, 0, 0, 0 };
        if (AHD_IMG[0] && base + (s + 1) * 512L <= AHD_LEN[0]) memcpy(data, AHD_IMG[0] + base + s * 512L, 512); else memset(data, 0, 512);
        it[0] = it[1] = it[2] = it[3] = 0xaa; it[4] = 0x44; it[5] = 0x89; it[6] = 0x44; it[7] = 0x89;
        hfl_oddeven(it + 8, info, 4);
        for (int i = 16; i < 48; i++) it[i] = 0xaa;
        hfl_oddeven(it + 64, data, 512);
        for (int i = 8; i < 48; i += 4) for (int k = 0; k < 4; k++) bc[k] ^= it[i + k];
        hfl_oddeven(it + 48, bc, 4);
        for (int i = 64; i < 1088; i += 4) for (int k = 0; k < 4; k++) dc[k] ^= it[i + k];
        hfl_oddeven(it + 56, dc, 4);
        for (int i = 8; i < 1088; i++) it[i] = hfl_clock(it[i], it[i - 1]);
        for (int e = 0; e < 2; e++) {                    /* the clock bit at the sector's two borders */
            long o = 8L * 1088 * (s + e), ob = ((o % (8L * HFL_TRACK)) + 8L * HFL_TRACK) % (8L * HFL_TRACK);
            int v = (hfl_bit(t, o - 1) || hfl_bit(t, o + 1)) ? 0 : 1;
            t[ob >> 3] = (uint8_t)((t[ob >> 3] & ~(0x80 >> (ob & 7))) | (v ? (0x80 >> (ob & 7)) : 0));
        }
    }
    HFL.tcyl = cyl; HFL.tside = side; HFL.tvalid = 1;
}

/* ---- the drive ---- */
static int hfl_selected(const HFloppy *f) { return !(f->prb & 0x08); }
static double hfl_speed(const HFloppy *f, double t) {
    double e = t - f->sw_t, s;
    if (f->motor) { s = f->sw_speed + 100.0 * e / HFL_START_CCK; return s > 100.0 ? 100.0 : s; }
    s = f->sw_speed - 100.0 * e / HFL_STOP_CCK; return s < 0.0 ? 0.0 : s;
}
static void hfl_motor(HFloppy *f, int on, double t) {
    if (f->motor == on) return;
    f->sw_speed = hfl_speed(f, t); f->sw_t = t; f->motor = on;
}
/* CIA-A PRA bits 2-5 as the drive drives them: /CHNG, /WPRO, /TK0, /RDY */
static uint8_t hfl_pra(void) {
    const HFloppy *f = &HFL; uint8_t r = 0xff; double t = h_abs();
    if (hfl_selected(f)) {
        double sp = hfl_speed(f, t);
        int idmode = (!f->motor && sp <= 0.0) || (f->motor && sp < 100.0);
        if (!idmode && AHD_IMG[0]) r &= (uint8_t)~0x20;          /* /RDY: full speed, or still running down (the drive's id bit of DF0 is 0: high while it speeds up) */
        if (f->cyl == 0) r &= (uint8_t)~0x10;
        if (!f->dskchange) r &= (uint8_t)~0x04;
    }
    return r;
}
static void hfl_prb(uint8_t oldv, uint8_t newv) {
    HFloppy *f = &HFL; double t = h_abs();
    int omtr = oldv & 0x80, osel = oldv & 0x08, ostep = oldv & 1, nmtr = newv & 0x80, nsel = newv & 0x08, nstep = newv & 1;
    f->prb = newv;
    if (osel && !nsel) { if (!omtr || !nmtr) hfl_motor(f, 1, t); else hfl_motor(f, 0, t); }
    if (!ostep && nstep && !osel) {
        if (AHD_IMG[0]) f->dskchange = 1;
        if (t - f->last_step >= HFL_STEP_GAP_CCK) {
            int moved = 0;
            if (newv & 2) { if (f->cyl > 0) { f->cyl--; moved = 1; } }
            else if (f->cyl < 83) { f->cyl++; moved = 1; }
            if (moved) { f->step_done = t + HFL_SETTLE_CCK; f->last_step = t; }
        }
    }
    f->side = (newv & 4) ? 0 : 1;
}

/* ---- the controller ---- */
static void hfl_fifo_put(HFloppy *f, uint8_t b) {
    if (f->fifocnt == 6) f->fifocnt -= 2;
    f->fifo = (f->fifo & 0x00ffffffffffffffull) << 8 | b; f->fifocnt++;
}
static void hfl_off(HFloppy *f) { f->state = 0; f->dsklen = 0; }
/* one byte passes the head at time t (colour clocks, absolute); dry: a copy run ahead - no interrupt, no index */
static void hfl_byte(HFloppy *f, double t, int dry) {
    uint8_t b = 0;
    if (hfl_selected(f)) {
        if (!AHD_IMG[0]) b = 0xff;
        else if (t < f->step_done) b = 0;
        else { if (!f->tvalid || f->tcyl != f->cyl || f->tside != f->side) { if (f == &HFL) hfl_encode(f->cyl, f->side); }
               b = (f->tvalid && f->tcyl == f->cyl && f->tside == f->side) ? f->trk[f->off] : HFL.trk[f->off]; }
        if (f->motor) { if (++f->off >= HFL_TRACK) { f->off = 0;
            if (!dry) { H_CIAB_ICR |= 0x10; h_irq_mark(); h_cia_raise(1); H_EVT_T = t; h_irq_mark(); } } }   /* the index pulse: CIA-B /FLG */
    }
    f->incoming = (uint16_t)(b | 0x8000); f->bytes++;
    for (int i = 7; i >= 0; i--) {
        f->datareg = (uint16_t)((f->datareg << 1) | ((b >> i) & 1));
        if (++f->dregcnt == 8) { hfl_fifo_put(f, (uint8_t)f->datareg); f->dregcnt = 0; }
        if (f->datareg == f->dsksync) {
            f->sync_t = t; f->syncs++;
            if (!dry) { h_irq_mark(); H_INTREQ |= 0x1000; H_EVT_T = t; h_irq_mark(); }
            if (f->state == 1) { f->dregcnt = 0; f->fifo = 0; f->fifocnt = 0; f->state = 2; }
        }
    }
}
/* a disk slot of the line at time t; slot: its index in the frame's map (-1: not in this frame's) */
static void hfl_dma(HFloppy *f, double t, long slot, int dry) {
    if ((f->dmacon & 0x0210) != 0x0210) return;
    if (!(f->dsklen & 0x3fff) || f->state != 2 || f->fifocnt < 2) return;
    f->fifocnt -= 2; uint16_t w = (uint16_t)((f->fifo >> (8 * f->fifocnt)) & 0xffff);
    if (slot >= 0) arek_bus_mark(arek_glue_bus(), (uint32_t)slot, AREK_BUS_DISK);
    if (!dry) { wr8_raw(f->dskpt, (uint32_t)(w >> 8)); wr8_raw(f->dskpt + 1, (uint32_t)(w & 0xff)); f->words++; }
    f->dskpt += 2;
    if (!(--f->dsklen & 0x3fff)) {
        if (!dry) { h_irq_mark(); H_INTREQ |= 0x0002; H_EVT_T = t; h_irq_mark(); }
        hfl_off(f);
    }
}
/* the next disk slot after `after` in the current frame: its time, *slot = its index in the map; 1e300 when the frame has none left */
static double hfl_next_slot(double after, long *slot) {
    double rel = after - H_PAULA.frame_base;
    long v = rel < 0 ? 0 : (long)floor(rel / HOST_HPOS); double h = rel < 0 ? -1 : rel - (double)v * HOST_HPOS;
    for (;; v++, h = -1) {
        if (v >= H_LINES) return 1e300;
        for (int k = 7; k <= 11; k += 2) if ((double)k > h) { *slot = v * HOST_HPOS + k; return H_PAULA.frame_base + (double)v * HOST_HPOS + k; }
    }
}
static void hfl_run_to(HFloppy *f, double t, int dry) {
    if (f->next_m < 0) { f->next_m = (long long)floor(h_abs() * 8.0) + 442; f->acc = 0; }
    for (;;) {
        double tb = (double)f->next_m / 8.0; long slot = -1; double td = hfl_next_slot(f->dma_done, &slot);
        if (tb > t && td > t) break;
        if (tb <= td) {
            hfl_byte(f, tb, dry);
            f->acc += HFL_BYTE_M; double r = floor(f->acc + 0.5); f->acc -= r; f->next_m += (long long)r;
        } else { hfl_dma(f, td, slot, dry); f->dma_done = td; }
    }
}
static void hfl_run(double t) { hfl_run_to(&HFL, t, 0); }
/* the slots the disk takes in the next colour clocks, marked in the map before the CPU's accesses reach them */
static void hfl_ahead(double t, double span) {
    if (HFL.state == 0 || (HFL.dmacon & 0x0210) != 0x0210) return;
    static HFloppy c; c = HFL; hfl_run_to(&c, t + span, 1);
}
static void hfl_dsklen(uint16_t v) {
    HFloppy *f = &HFL; uint16_t old = f->dsklen;
    f->dsklen = v;
    if (!(v & 0x8000)) { hfl_off(f); f->fifo = 0; f->fifocnt = 0; }
    if (old & v & 0x8000) {
        if (!(f->dsklen & 0x3fff)) { h_irq_mark(); H_INTREQ |= 0x0002; H_EVT_T = h_abs(); h_irq_mark(); return; }
        if (old & v & 0x4000) { hfl_off(f); return; }               /* a write to the disk: not modelled */
        f->state = (f->adkcon & 0x0400) ? 1 : 2; f->fifo = 0; f->fifocnt = 0;
    }
}
/* a CPU write to a custom register the controller has */
static void hfl_reg_write(uint32_t off, uint16_t v) {
    HFloppy *f = &HFL;
    if (off == 0x020 || off == 0x022 || off == 0x024 || off == 0x07e || off == 0x09e || off == 0x096) hfl_run(h_abs());
    if (off == 0x020) f->dskpt = (f->dskpt & 0x0000ffffu) | ((uint32_t)(v & 0x001f) << 16);
    else if (off == 0x022) f->dskpt = (f->dskpt & 0xffff0000u) | (v & 0xfffeu);
    else if (off == 0x024) hfl_dsklen(v);
    else if (off == 0x07e) f->dsksync = v;
    else if (off == 0x09e) { if (v & 0x8000) f->adkcon |= v & 0x7fff; else f->adkcon &= (uint16_t)~v; }
    else if (off == 0x096) { if (v & 0x8000) f->dmacon |= v & 0x7fff; else f->dmacon &= (uint16_t)~v; }
}
static uint16_t hfl_dskbytr(void) {
    HFloppy *f = &HFL; hfl_run(h_abs());
    uint16_t r = f->incoming;
    if ((f->dmacon & 0x0210) == 0x0210 && f->state != 0) r |= 0x4000;
    if (f->dsklen & 0x4000) r |= 0x2000;
    if (h_abs() - f->sync_t <= 2.0 * 28.0 / 8.0) r |= 0x1000;
    f->incoming &= 0x7fff;
    return r;
}
#endif
