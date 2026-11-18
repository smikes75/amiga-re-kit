/* arek_audio.h - the sound of the four channels (arek_bus_paula.h sample events) as 48 kHz stereo int16: each channel
 * holds its byte * volume from the time it was output, left = channels 0 and 3, right = 1 and 2, as the Amiga wires
 * them; no filters (the page applies the contract's, wb-zvuk.js). Header-only, MIT. No game data.
 *   ara_event(ch, t, value) from the Paula sample callback; ara_until(t) renders the samples up to absolute CCK t into
 *   ARA_BUF (ARA_N stereo frames); ara_reset() at a new start (otherwise the sample clock stays behind the frame time).
 * 0.8.6 (Alien Breed II G52): ARA_GAIN[ch][side] places each channel in the stereo picture - default {1,0} {0,1} {0,1} {1,0},
 *   with which the output is bit for bit the old one (integer path). ara_gain(ch, l, r) sets it at once; ara_gain_to(ch, l, r)
 *   ramps it linearly, sample by sample, across the next ara_until() call (an effect fading a channel or moving it to the
 *   other side by the game's state, once a frame). With a matrix other than the default the mix is clamped to int16.
 * 1.0.93 (SWIV, the user 2026-11-18: SWIV-projekt's extra voices and mixer): channels 4-7 are the host's output-only voices
 *   (arek_host.h host_voice_*: a second Paula that never touches the machine) - their events come as ara_event(4 + v, ...),
 *   their default places are those of 0-3 (4 and 7 left, 5 and 6 right). While a voice sounds or a gain is above 1 the mix
 *   goes through a compressor-limiter (stereo-linked, -6 dBFS, ratio 8, knee 6 dB, attack 3 ms, release 150 ms - the
 *   values SWIV-projekt tuned) before the int16 clamp; otherwise nothing changes: the four channels at the default matrix
 *   are bit for bit the old mix, any other matrix at most 1 the old clamped float mix. ara_limit_on() says whether the
 *   last ara_until() used it, ARA_LIMIT_MIN the lowest gain it applied (statistics).
 *   A channel's mixer level ARA_LVL[ch] (default 1, 0..4) multiplies its matrix row from a given time on:
 *   ara_level_at(ch, t, level) is an event in the same time order as the samples (a game's hook sets the level of the
 *   sound kind that starts on a channel at the start itself - arek_host.h host_aud_tag). Levels of 1 keep the plain mix. */
#ifndef AREK_AUDIO_H
#define AREK_AUDIO_H
#include <stdint.h>
#include <string.h>
#include <math.h>
#ifndef ARA_RATE
#define ARA_RATE 48000.0
#endif
#define ARA_CCK 3546895.0                  /* PAL colour clocks per second */
#define ARA_MAX 16384
#define ARA_EVENTS 8192
#define ARA_CH 8                           /* 1.0.93: 0-3 Paula, 4-7 the host's voices */
static int16_t ARA_BUF[ARA_MAX * 2];
static int ARA_N = 0;
static struct { double t; int ch, v; } ARA_EV[ARA_EVENTS];
static int ARA_NEV = 0;
static int ARA_LEVEL[ARA_CH];
static double ARA_T = -1;                  /* absolute time of the next sample (CCK) */
static double ARA_GAIN[ARA_CH][2] = {{1, 0}, {0, 1}, {0, 1}, {1, 0}, {1, 0}, {0, 1}, {0, 1}, {1, 0}};   /* channel -> left, right (the Amiga's wiring) */
static double ARA_GAIN_TO[ARA_CH][2];
static double ARA_LVL[ARA_CH] = {1, 1, 1, 1, 1, 1, 1, 1};   /* 1.0.93: the mixer level of each channel (ara_level_at) */
#define ARA_LVL_ONE 4096                   /* a level event's value: level * 4096 */
static double ARA_ENV = 0;                 /* 1.0.93: the limiter's envelope (peak, 0..1+) */
static int ARA_LIMITED = 0;                /* 1.0.93: the last ara_until() went through the limiter */
static double ARA_LIMIT_MIN = 1;           /* 1.0.93: the lowest gain the limiter applied since ara_reset (statistics) */
static int ARA_RAMP = 0;                   /* ARA_GAIN_TO is the matrix at the end of the next ara_until() */
static int ara_gain_default(void) {
    static const double d[ARA_CH][2] = {{1, 0}, {0, 1}, {0, 1}, {1, 0}, {1, 0}, {0, 1}, {0, 1}, {1, 0}};
    return memcmp(ARA_GAIN, d, sizeof d) == 0;
}
static void ara_gain(int ch, double l, double r) { ARA_GAIN[ch & 7][0] = l; ARA_GAIN[ch & 7][1] = r; }
static void ara_gain_to(int ch, double l, double r) {
    if (!ARA_RAMP) memcpy(ARA_GAIN_TO, ARA_GAIN, sizeof ARA_GAIN);
    ARA_GAIN_TO[ch & 7][0] = l; ARA_GAIN_TO[ch & 7][1] = r; ARA_RAMP = 1;
}
static int ara_limit_on(void) { return ARA_LIMITED; }
/* 1.0.93: the compressor-limiter's gain for the envelope e (0..1+ of full scale): -6 dBFS, ratio 8, knee 6 dB */
static double ara_limit_gain(double e) {
    if (e <= 1e-9) return 1;
    const double T = -6.0, R = 8.0, K = 6.0; double x = 20.0 * log10(e), g;
    if (x <= T - K / 2) return 1;
    if (x >= T + K / 2) g = (T + (x - T) / R) - x;
    else { double d = x - T + K / 2; g = (1.0 / R - 1.0) * d * d / (2.0 * K); }
    return pow(10.0, g / 20.0);
}
static void ara_event(int ch, double t, int value) {
    ch &= 7;
    if (ARA_NEV < ARA_EVENTS) { ARA_EV[ARA_NEV].t = t; ARA_EV[ARA_NEV].ch = ch; ARA_EV[ARA_NEV].v = value; ARA_NEV++; }
    else ARA_LEVEL[ch] = value;
}
/* 1.0.93: channel ch's mixer level from time t on (0..4; queued with the samples: event channel 8 + ch) */
static void ara_level_at(int ch, double t, double level) {
    int q = (int)lrint((level < 0 ? 0 : level > 4 ? 4 : level) * ARA_LVL_ONE);
    if (ARA_NEV < ARA_EVENTS) { ARA_EV[ARA_NEV].t = t; ARA_EV[ARA_NEV].ch = 8 + (ch & 7); ARA_EV[ARA_NEV].v = q; ARA_NEV++; }
    else ARA_LVL[ch & 7] = (double)q / ARA_LVL_ONE;
}
static int ara_levels_one(void) { for (int c = 0; c < ARA_CH; c++) if (ARA_LVL[c] != 1.0) return 0; return 1; }
static void ara_reset(void) { ARA_T = -1; ARA_N = 0; ARA_NEV = 0; ARA_RAMP = 0; memset(ARA_LEVEL, 0, sizeof ARA_LEVEL); ARA_ENV = 0; ARA_LIMITED = 0; ARA_LIMIT_MIN = 1; }   /* the gains stay */
/* samples up to t: the events are in time order per channel, not across channels - sort by insertion */
static void ara_until(double t) {
    if (ARA_T < 0) ARA_T = t;
    for (int i = 1; i < ARA_NEV; i++) { int j = i; while (j > 0 && ARA_EV[j - 1].t > ARA_EV[j].t) { __typeof__(ARA_EV[0]) x = ARA_EV[j]; ARA_EV[j] = ARA_EV[j - 1]; ARA_EV[j - 1] = x; j--; } }
    int e = 0; double step = ARA_CCK / ARA_RATE;
    int plain = !ARA_RAMP && ara_gain_default() && ara_levels_one();
    for (int i = 0; i < ARA_NEV && plain; i++) if (ARA_EV[i].ch >= 8 && ARA_EV[i].v != ARA_LVL_ONE) plain = 0;
    int live = 0;                                             /* 1.0.93: a host voice sounds in this call, or a gain or a level is above 1 */
    for (int c = 4; c < ARA_CH; c++) if (ARA_LEVEL[c]) live = 1;
    for (int i = 0; i < ARA_NEV && !live; i++) if ((ARA_EV[i].ch >= 4 && ARA_EV[i].ch < 8) || (ARA_EV[i].ch >= 8 && ARA_EV[i].v > ARA_LVL_ONE)) live = 1;
    for (int c = 0; c < ARA_CH && !live; c++) { if (ARA_LVL[c] > 1) live = 1;
        for (int k2 = 0; k2 < 2; k2++) if (ARA_GAIN[c][k2] > 1 || (ARA_RAMP && ARA_GAIN_TO[c][k2] > 1)) live = 1; }
    if (!live && ara_limit_gain(ARA_ENV) < 0.9999) live = 1;   /* the limiter lets go by its release, not at once (no jump in level) */
    if (!live) ARA_ENV = 0;
    ARA_LIMITED = live;
    const double aA = 1.0 - exp(-1.0 / (0.003 * ARA_RATE)), aR = 1.0 - exp(-1.0 / (0.150 * ARA_RATE));
    long n = 0, k = 0;
    if (ARA_RAMP) { double tt = ARA_T; while (tt <= t) { n++; tt += step; } }   /* the samples of this call, as the loop below counts them */
    while (ARA_T <= t) {
        while (e < ARA_NEV && ARA_EV[e].t <= ARA_T) {
            if (ARA_EV[e].ch >= 8) ARA_LVL[ARA_EV[e].ch - 8] = (double)ARA_EV[e].v / ARA_LVL_ONE; else ARA_LEVEL[ARA_EV[e].ch] = ARA_EV[e].v;
            e++; }
        if (ARA_N < ARA_MAX) {
            if (plain && !live) {
                int l = ARA_LEVEL[0] + ARA_LEVEL[3], r = ARA_LEVEL[1] + ARA_LEVEL[2];
                ARA_BUF[2 * ARA_N] = (int16_t)(l * 2); ARA_BUF[2 * ARA_N + 1] = (int16_t)(r * 2);
            } else {
                double f = ARA_RAMP && n > 0 ? (double)(k + 1) / (double)n : 1.0, l = 0, r = 0;
                for (int c = 0; c < (live ? ARA_CH : 4); c++) {
                    double gl = ARA_GAIN[c][0], gr = ARA_GAIN[c][1];
                    if (ARA_RAMP) { gl += (ARA_GAIN_TO[c][0] - gl) * f; gr += (ARA_GAIN_TO[c][1] - gr) * f; }
                    l += ARA_LEVEL[c] * gl * ARA_LVL[c]; r += ARA_LEVEL[c] * gr * ARA_LVL[c];
                }
                l *= 2; r *= 2;
                if (live) {                                   /* 1.0.93: stereo-linked compressor-limiter before the clamp */
                    double x = fabs(l) > fabs(r) ? fabs(l) : fabs(r); x /= 32768.0;
                    ARA_ENV += (x - ARA_ENV) * (x > ARA_ENV ? aA : aR);
                    double g = ara_limit_gain(ARA_ENV); if (g < ARA_LIMIT_MIN) ARA_LIMIT_MIN = g;
                    l *= g; r *= g;
                }
                if (l > 32767) l = 32767; else if (l < -32768) l = -32768;
                if (r > 32767) r = 32767; else if (r < -32768) r = -32768;
                ARA_BUF[2 * ARA_N] = (int16_t)lrint(l); ARA_BUF[2 * ARA_N + 1] = (int16_t)lrint(r);
            }
            ARA_N++;
        }
        ARA_T += step; k++;
    }
    while (e < ARA_NEV) { if (ARA_EV[e].ch >= 8) ARA_LVL[ARA_EV[e].ch - 8] = (double)ARA_EV[e].v / ARA_LVL_ONE; else ARA_LEVEL[ARA_EV[e].ch] = ARA_EV[e].v; e++; }
    ARA_NEV = 0;
    if (ARA_RAMP) { memcpy(ARA_GAIN, ARA_GAIN_TO, sizeof ARA_GAIN); ARA_RAMP = 0; }
}
#endif
