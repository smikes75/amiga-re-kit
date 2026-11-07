// arek difftest: Moira, vAmiga's 68000 (Dirk W. Hoffmann, MIT), as the reference for one instruction at a time.
//   moira_diff IMAGE CASES OUT
// IMAGE is the RAM. A line of CASES (hex): pc sp sr stop1 stop2 self_end d0-d7 a0-a6 pokes (addr=hexbytes,... or -).
// The CPU starts in supervisor mode at pc and runs until it reaches stop1 or stop2. A line of OUT:
//   flags cycles pc sr d0-d7 a0-a7 memory (addr=hexbyte,... against IMAGE, or -)
// flags: 1 an exception other than TRAP, 2 an access above the mirrored chip RAM, 4 a write into the instruction itself,
// 8 no stop reached. Chip RAM repeats up to $200000 as in the translation's runtime; above it reads give 0, writes are
// dropped. The run's memory comes back from a journal, so a case costs what it touches.
#include "Moira.h"
#include <map>
#include <string>
#include <vector>

namespace vamiga::moira {
enum { F_EXC = 1, F_OUT = 2, F_SELF = 4, F_RUN = 8 };
static uint8_t *MEM;
static uint32_t MEMSZ, R_SP, R_PC, SELF_LO, SELF_HI;
static int FLAGS;
static std::vector<std::pair<uint32_t, uint8_t>> JOURNAL;

static inline bool at(uint32_t a, uint32_t &o) {
    a &= 0xffffff;
    if (a >= 0x200000) { FLAGS |= F_OUT; return false; }
    o = a % MEMSZ;
    return true;
}
static inline void put(uint32_t a, uint8_t v) {
    uint32_t o;
    if (!at(a, o)) return;
    if (o >= SELF_LO && o < SELF_HI) FLAGS |= F_SELF;
    JOURNAL.push_back({o, MEM[o]});
    MEM[o] = v;
}
void Moira::sync(int cycles) { clock += cycles; }
u8 Moira::read8(u32 a) const { uint32_t o; return at(a, o) ? MEM[o] : 0; }
u16 Moira::read16(u32 a) const { uint32_t o; return at(a, o) ? (u16)((MEM[o] << 8) | MEM[(o + 1) % MEMSZ]) : 0; }
u32 Moira::read32(u32 a) const { return ((u32)read16(a) << 16) | read16(a + 2); }
u16 Moira::read16OnReset(u32 a) const {
    switch (a) { case 0: return R_SP >> 16; case 2: return R_SP & 0xffff; case 4: return R_PC >> 16; case 6: return R_PC & 0xffff; }
    return read16(a);
}
u16 Moira::read16Dasm(u32 a) const { return read16(a); }
void Moira::write8(u32 a, u8 v) const { put(a, v); }
void Moira::write16(u32 a, u16 v) const { put(a, v >> 8); put(a + 1, v & 0xff); }
void Moira::write32(u32 a, u32 v) const { write16(a, v >> 16); write16(a + 2, v & 0xffff); }
u8 Moira::dsack(u32) const { return 0; }
u16 Moira::readIrqUserVector(u8) const { return 0; }
void Moira::cpuDidReset() { }
void Moira::cpuDidHalt() { FLAGS |= F_EXC; }
void Moira::willExecute(const char *, Instr, Mode, Size, u16) { }
void Moira::didExecute(const char *, Instr, Mode, Size, u16) { }
void Moira::willExecute(M68kException exc, u16) { if (exc != M68kException::TRAP) FLAGS |= F_EXC; }
void Moira::didExecute(M68kException, u16) { }
void Moira::willInterrupt(u8) { }
void Moira::didJumpToVector(int, u32) { }
void Moira::didChangeCACR(u32) { }
void Moira::didChangeCAAR(u32) { }
void Moira::didReachSoftstop(u32) { }
void Moira::didReachBreakpoint(u32) { }
void Moira::didReachWatchpoint(u32) { }
void Moira::didReachCatchpoint(u8) { }
void Moira::didReachSoftwareTrap(u32) { }
void Moira::didLogInstruction(const Registers &) { }

static std::vector<uint8_t> load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    std::vector<uint8_t> v;
    uint8_t b[65536];
    size_t n;
    while ((n = fread(b, 1, sizeof b, f)) > 0) v.insert(v.end(), b, b + n);
    fclose(f);
    return v;
}
static void pokes(const char *s) {
    if (*s == '-') return;
    while (*s) {
        char *e;
        uint32_t a = (uint32_t)strtoul(s, &e, 16);
        s = e + 1;
        for (; s[0] && s[0] != ','; s += 2, a++) {
            char h[3] = { s[0], s[1], 0 };
            uint32_t o = a % MEMSZ;
            JOURNAL.push_back({o, MEM[o]});
            MEM[o] = (uint8_t)strtoul(h, nullptr, 16);
        }
        if (*s == ',') s++;
    }
}
static int run(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--list")) {          // the opcodes Moira's 68000 executes, with their mnemonics
        static uint8_t ram[64];
        MEM = ram; MEMSZ = sizeof ram;
        alignas(16) static char room0[16];
        Moira cpu0(*reinterpret_cast<Amiga *>(room0));
        cpu0.setModel(Model::M68000);
        cpu0.setDasmSyntax(Syntax::MOIRA);
        char t[128];
        for (int op = 0; op < 0x10000; op++) {
            if (cpu0.getInstrInfo((u16)op).I == Instr::ILLEGAL || cpu0.getInstrInfo((u16)op).I == Instr::LINE_A || cpu0.getInstrInfo((u16)op).I == Instr::LINE_F) continue;
            ram[0] = (uint8_t)(op >> 8); ram[1] = (uint8_t)op;
            cpu0.disassemble(t, 0);
            printf("%04x %s\n", op, t);
        }
        return 0;
    }
    if (argc != 4) { fprintf(stderr, "moira_diff IMAGE CASES OUT\n"); return 1; }
    std::vector<uint8_t> image = load(argv[1]);
    MEM = image.data(); MEMSZ = (uint32_t)image.size();
    FILE *in = fopen(argv[2], "r"), *out = fopen(argv[3], "w");
    if (!in || !out) { perror("moira_diff"); return 1; }
    alignas(16) static char room[16];
    Moira cpu(*reinterpret_cast<Amiga *>(room));
    cpu.setModel(Model::M68000);
    static char line[8192], pk[4096];
    while (fgets(line, sizeof line, in)) {
        uint32_t pc, sp, sr, s1, s2, se, d[8], a[7];
        int used = 0;
        if (sscanf(line, "%x %x %x %x %x %x%n", &pc, &sp, &sr, &s1, &s2, &se, &used) != 6) continue;
        const char *p = line + used;
        for (int i = 0; i < 8; i++) { sscanf(p, "%x%n", &d[i], &used); p += used; }
        for (int i = 0; i < 7; i++) { sscanf(p, "%x%n", &a[i], &used); p += used; }
        sscanf(p, "%4095s", pk);
        JOURNAL.clear();
        pokes(pk);
        R_SP = sp; R_PC = pc; SELF_LO = pc; SELF_HI = se;
        cpu.reset();
        for (int i = 0; i < 8; i++) cpu.setD(i, d[i]);
        for (int i = 0; i < 7; i++) cpu.setA(i, a[i]);
        cpu.setSR((u16)sr);
        cpu.setUSP(sp);
        FLAGS = 0;
        i64 c0 = cpu.getClock();
        bool stopped = false;
        for (int n = 0; n < 8 && !(FLAGS & F_EXC); n++) {
            cpu.execute();
            if (cpu.getPC() == s1 || cpu.getPC() == s2) { stopped = true; break; }
        }
        if (!stopped) FLAGS |= F_RUN;
        fprintf(out, "%x %llx %x %x", FLAGS, (unsigned long long)(cpu.getClock() - c0), cpu.getPC(), cpu.getSR());
        for (int i = 0; i < 8; i++) fprintf(out, " %x", cpu.getD(i));
        for (int i = 0; i < 8; i++) fprintf(out, " %x", cpu.getA(i));
        std::map<uint32_t, uint8_t> first;
        for (auto &j : JOURNAL) first.emplace(j.first, j.second);
        std::string mem;
        for (auto &kv : first)
            if (MEM[kv.first] != kv.second) {
                char t[32];
                snprintf(t, sizeof t, "%s%x=%02x", mem.empty() ? "" : ",", kv.first, MEM[kv.first]);
                mem += t;
            }
        fprintf(out, " %s\n", mem.empty() ? "-" : mem.c_str());
        for (auto it = JOURNAL.rbegin(); it != JOURNAL.rend(); ++it) MEM[it->first] = it->second;
    }
    fclose(in); fclose(out);
    return 0;
}
}
int main(int argc, char **argv) { return vamiga::moira::run(argc, argv); }
