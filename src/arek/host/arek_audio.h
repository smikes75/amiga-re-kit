/* arek_audio.h - the sound of the four channels (arek_bus_paula.h sample events) as 48 kHz stereo int16: each channel
 * holds its byte * volume from the time it was output, left = channels 0 and 3, right = 1 and 2, as the Amiga wires
 * them; no filters (the page applies the contract's, wb-zvuk.js). Header-only, MIT. No game data.
 *   ara_event(ch, t, value) from the Paula sample callback; ara_until(t) renders the samples up to absolute CCK t into
 *   ARA_BUF (ARA_N stereo frames); ara_reset() at a new start (otherwise the sample clock stays behind the frame time).
 * 0.8.6 (Alien Breed II G52): ARA_GAIN[ch][side] places each channel in the stereo picture - default {1,0} {0,1} {0,1} {1,0},
 *   with which the output is bit for bit the old one (integer path). ara_gain(ch, l, r) sets it at once; ara_gain_to(ch, l, r)
 *   ramps it linearly, sample by sample, across the next ara_until() call (an effect fading a channel or moving it to the
 *   other side by the game's state, once a frame). With a matrix other than the default the mix is clamped to int16. */
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
static int16_t ARA_BUF[ARA_MAX * 2];
static int ARA_N = 0;
static struct { double t; int ch, v; } ARA_EV[ARA_EVENTS];
static int ARA_NEV = 0;
static int ARA_LEVEL[4];
static double ARA_T = -1;                  /* absolute time of the next sample (CCK) */
static double ARA_GAIN[4][2] = {{1, 0}, {0, 1}, {0, 1}, {1, 0}};   /* channel -> left, right (the Amiga's wiring) */
static double ARA_GAIN_TO[4][2];
static int ARA_RAMP = 0;                   /* ARA_GAIN_TO is the matrix at the end of the next ara_until() */
static int ara_gain_default(void) {
    static const double d[4][2] = {{1, 0}, {0, 1}, {0, 1}, {1, 0}};
    return memcmp(ARA_GAIN, d, sizeof d) == 0;
}
static void ara_gain(int ch, double l, double r) { ARA_GAIN[ch & 3][0] = l; ARA_GAIN[ch & 3][1] = r; }
static void ara_gain_to(int ch, double l, double r) {
    if (!ARA_RAMP) memcpy(ARA_GAIN_TO, ARA_GAIN, sizeof ARA_GAIN);
    ARA_GAIN_TO[ch & 3][0] = l; ARA_GAIN_TO[ch & 3][1] = r; ARA_RAMP = 1;
}
static void ara_event(int ch, double t, int value) {
    if (ARA_NEV < ARA_EVENTS) { ARA_EV[ARA_NEV].t = t; ARA_EV[ARA_NEV].ch = ch; ARA_EV[ARA_NEV].v = value; ARA_NEV++; }
    else ARA_LEVEL[ch] = value;
}
static void ara_reset(void) { ARA_T = -1; ARA_N = 0; ARA_NEV = 0; ARA_RAMP = 0; memset(ARA_LEVEL, 0, sizeof ARA_LEVEL); }   /* the gains stay */
/* samples up to t: the events are in time order per channel, not across channels - sort by insertion */
static void ara_until(double t) {
    if (ARA_T < 0) ARA_T = t;
    for (int i = 1; i < ARA_NEV; i++) { int j = i; while (j > 0 && ARA_EV[j - 1].t > ARA_EV[j].t) { __typeof__(ARA_EV[0]) x = ARA_EV[j]; ARA_EV[j] = ARA_EV[j - 1]; ARA_EV[j - 1] = x; j--; } }
    int e = 0; double step = ARA_CCK / ARA_RATE;
    int plain = !ARA_RAMP && ara_gain_default();
    long n = 0, k = 0;
    if (ARA_RAMP) { double tt = ARA_T; while (tt <= t) { n++; tt += step; } }   /* the samples of this call, as the loop below counts them */
    while (ARA_T <= t) {
        while (e < ARA_NEV && ARA_EV[e].t <= ARA_T) { ARA_LEVEL[ARA_EV[e].ch] = ARA_EV[e].v; e++; }
        if (ARA_N < ARA_MAX) {
            if (plain) {
                int l = ARA_LEVEL[0] + ARA_LEVEL[3], r = ARA_LEVEL[1] + ARA_LEVEL[2];
                ARA_BUF[2 * ARA_N] = (int16_t)(l * 2); ARA_BUF[2 * ARA_N + 1] = (int16_t)(r * 2);
            } else {
                double f = ARA_RAMP && n > 0 ? (double)(k + 1) / (double)n : 1.0, l = 0, r = 0;
                for (int c = 0; c < 4; c++) {
                    double gl = ARA_GAIN[c][0], gr = ARA_GAIN[c][1];
                    if (ARA_RAMP) { gl += (ARA_GAIN_TO[c][0] - gl) * f; gr += (ARA_GAIN_TO[c][1] - gr) * f; }
                    l += ARA_LEVEL[c] * gl; r += ARA_LEVEL[c] * gr;
                }
                l *= 2; r *= 2;
                if (l > 32767) l = 32767; else if (l < -32768) l = -32768;
                if (r > 32767) r = 32767; else if (r < -32768) r = -32768;
                ARA_BUF[2 * ARA_N] = (int16_t)lrint(l); ARA_BUF[2 * ARA_N + 1] = (int16_t)lrint(r);
            }
            ARA_N++;
        }
        ARA_T += step; k++;
    }
    while (e < ARA_NEV) { ARA_LEVEL[ARA_EV[e].ch] = ARA_EV[e].v; e++; }
    ARA_NEV = 0;
    if (ARA_RAMP) { memcpy(ARA_GAIN, ARA_GAIN_TO, sizeof ARA_GAIN); ARA_RAMP = 0; }
}
#endif
