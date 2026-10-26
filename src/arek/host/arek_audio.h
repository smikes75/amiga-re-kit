/* arek_audio.h - the sound of the four channels (arek_bus_paula.h sample events) as 48 kHz stereo int16: each channel
 * holds its byte * volume from the time it was output, left = channels 0 and 3, right = 1 and 2, as the Amiga wires
 * them; no filters (the page applies the contract's, wb-zvuk.js). Header-only, MIT. No game data.
 *   ara_event(ch, t, value) from the Paula sample callback; ara_until(t) renders the samples up to absolute CCK t into
 *   ARA_BUF (ARA_N stereo frames); ara_reset() at a new start (otherwise the sample clock stays behind the frame time). */
#ifndef AREK_AUDIO_H
#define AREK_AUDIO_H
#include <stdint.h>
#include <string.h>
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
static void ara_event(int ch, double t, int value) {
    if (ARA_NEV < ARA_EVENTS) { ARA_EV[ARA_NEV].t = t; ARA_EV[ARA_NEV].ch = ch; ARA_EV[ARA_NEV].v = value; ARA_NEV++; }
    else ARA_LEVEL[ch] = value;
}
static void ara_reset(void) { ARA_T = -1; ARA_N = 0; ARA_NEV = 0; memset(ARA_LEVEL, 0, sizeof ARA_LEVEL); }
/* samples up to t: the events are in time order per channel, not across channels - sort by insertion */
static void ara_until(double t) {
    if (ARA_T < 0) ARA_T = t;
    for (int i = 1; i < ARA_NEV; i++) { int j = i; while (j > 0 && ARA_EV[j - 1].t > ARA_EV[j].t) { __typeof__(ARA_EV[0]) x = ARA_EV[j]; ARA_EV[j] = ARA_EV[j - 1]; ARA_EV[j - 1] = x; j--; } }
    int e = 0; double step = ARA_CCK / ARA_RATE;
    while (ARA_T <= t) {
        while (e < ARA_NEV && ARA_EV[e].t <= ARA_T) { ARA_LEVEL[ARA_EV[e].ch] = ARA_EV[e].v; e++; }
        if (ARA_N < ARA_MAX) {
            int l = ARA_LEVEL[0] + ARA_LEVEL[3], r = ARA_LEVEL[1] + ARA_LEVEL[2];
            ARA_BUF[2 * ARA_N] = (int16_t)(l * 2); ARA_BUF[2 * ARA_N + 1] = (int16_t)(r * 2); ARA_N++;
        }
        ARA_T += step;
    }
    while (e < ARA_NEV) { ARA_LEVEL[ARA_EV[e].ch] = ARA_EV[e].v; e++; }
    ARA_NEV = 0;
}
#endif
