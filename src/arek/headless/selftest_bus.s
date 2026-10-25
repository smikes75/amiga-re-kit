| selftest_bus.s - the bus self-test program (arek selftest bus): a display of 5 lores planes, a sprite, a
| copper list with waits, and a loop of three blits (A->D, a four-channel cookie with a shift, a D-only clear)
| separated by stack traffic. Runs at $40000 (the boot block copies it there). GNU as, -m68000.
        .text
start:  lea     0xdff000,%a6
        move.w  #0x7fff,0x9a(%a6)       | INTENA off
        move.w  #0x7fff,0x96(%a6)       | DMACON off
        move.l  #coplist,0x80(%a6)
        move.w  %d0,0x88(%a6)           | COPJMP1
        move.w  #0x87e0,0x96(%a6)       | DMAEN BLTPRI BPLEN COPEN BLTEN SPREN (the CPU waits during a blit, as games do)
        move.w  #-1,0x44(%a6)           | AFWM
        move.w  #-1,0x46(%a6)           | ALWM
        clr.w   0x60(%a6)               | BLTCMOD
        clr.w   0x62(%a6)               | BLTBMOD
        clr.w   0x64(%a6)               | BLTAMOD
        clr.w   0x66(%a6)               | BLTDMOD
        moveq   #0,%d7
loop:   move.l  #0x10000,0x50(%a6)      | blit 1: A -> D, 32 rows x 20 words
        move.l  #0x20000,0x54(%a6)
        move.w  #0x09f0,0x40(%a6)
        clr.w   0x42(%a6)
        move.w  #0x0814,0x58(%a6)
w1:     btst    #6,0x02(%a6)            | DMACONR BBUSY
        bne.s   w1
        move.l  #0x10000,0x50(%a6)      | blit 2: A B C -> D cookie, minterm $ca, B shifted by 1, 16 rows x 10 words
        move.l  #0x12000,0x4c(%a6)
        move.l  #0x14000,0x48(%a6)
        move.l  #0x22000,0x54(%a6)
        move.w  #0x0fca,0x40(%a6)
        move.w  #0x1000,0x42(%a6)
        move.w  #0x040a,0x58(%a6)
w2:     btst    #6,0x02(%a6)
        bne.s   w2
        move.l  #0x24000,0x54(%a6)      | blit 3: D only (clear), 64 rows x 40 words
        move.w  #0x0100,0x40(%a6)
        clr.w   0x42(%a6)
        move.w  #0x1028,0x58(%a6)
w3:     btst    #6,0x02(%a6)
        bne.s   w3
        lea     0x30000,%a0             | CPU traffic between blits
        movem.l %d0-%d7/%a1-%a5,-(%a0)
        movem.l (%a0)+,%d0-%d7/%a1-%a5
        addq.w  #1,%d7
        move.w  %d7,0x3fffe
        bra     loop
        .even
coplist:
        .word   0x0100,0x5200           | BPLCON0: 5 planes, lores
        .word   0x008e,0x2c81, 0x0090,0xf4c1, 0x0092,0x0038, 0x0094,0x00d0
        .word   0x0108,0x0000, 0x010a,0x0000
        .word   0x00e0,0x0005,0x00e2,0x0000     | planes at $50000 + k * $2000 (zeros)
        .word   0x00e4,0x0005,0x00e6,0x2000
        .word   0x00e8,0x0005,0x00ea,0x4000
        .word   0x00ec,0x0005,0x00ee,0x6000
        .word   0x00f0,0x0005,0x00f2,0x8000
        .word   0x0120,0x0004,0x0122,spr0-start
        .word   0x0124,0x0004,0x0126,nul-start
        .word   0x0128,0x0004,0x012a,nul-start
        .word   0x012c,0x0004,0x012e,nul-start
        .word   0x0130,0x0004,0x0132,nul-start
        .word   0x0134,0x0004,0x0136,nul-start
        .word   0x0138,0x0004,0x013a,nul-start
        .word   0x013c,0x0004,0x013e,nul-start
        .word   0x0180,0x0000, 0x0182,0x0f00, 0x0184,0x00f0, 0x0186,0x000f
        .word   0x6c07,0xfffe, 0x0180,0x0005
        .word   0x8c07,0xfffe, 0x0180,0x0050
        .word   0xa007,0xfffe, 0x0180,0x0500
        .word   0xc007,0xfffe, 0x0180,0x0055
        .word   0xffff,0xfffe
spr0:   .word   0x5080,0x7000           | v $50..$70, h $80
        .rept 32
        .word   0xf00f,0x0ff0
        .endr
        .word   0,0
nul:    .word   0,0
