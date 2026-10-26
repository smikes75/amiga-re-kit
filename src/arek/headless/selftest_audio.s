| selftest_audio.s - the Paula self-test program (arek selftest audio): four channels with different periods, lengths
| and volumes, switched on and off by a script keyed to the frame counter (DMACON writes at line 100 and line 200 of a
| frame, a period and volume change mid-run, the whole setup rewritten every 16 frames so any log window sees it);
| no display DMA. Runs at $40000 (the boot block copies it there). GNU as, -m68000.
        .text
start:  lea     0xdff000,%a6
        move.w  #0x7fff,0x9a(%a6)       | INTENA off
        move.w  #0x7fff,0x96(%a6)       | all DMA off
        move.w  #0x8200,0x96(%a6)       | DMAEN
        moveq   #0,%d7
loop:   moveq   #100,%d0
        bsr     wait                    | line 100 of the frame
        addq.w  #1,%d7
        move.w  %d7,0x3fffe
        move.w  %d7,%d1
        and.w   #15,%d1
        bne.s   0f
        bsr     setup                   | frame 0 of 16: the channels' registers (DMA is off since frame 12)
0:      add.w   %d1,%d1
        move.w  tab(%pc,%d1.w),%d1      | the script: a DMACON value per frame mod 16, 0 = nothing
        beq.s   1f
        move.w  %d1,0x96(%a6)
1:      move.w  %d7,%d1
        and.w   #15,%d1
        cmp.w   #9,%d1                  | frame 9: a new period and volume on channel 0 while it plays
        bne.s   2f
        move.w  #150,0xa6(%a6)
        move.w  #48,0xa8(%a6)
2:      move.w  #200,%d0
        bsr     wait                    | line 200: a second write point in the same frame
        move.w  %d7,%d1
        and.w   #15,%d1
        cmp.w   #5,%d1
        bne.s   3f
        move.w  #0x0002,0x96(%a6)       | frame 5: channel 1 off (on since line 100 of frame 4)
3:      cmp.w   #11,%d1
        bne.s   loop
        move.w  #0x800f,0x96(%a6)       | frame 11: everything on at line 200
        bra     loop
tab:    .word   0x0000, 0x0000, 0x8001, 0x0000, 0x8002, 0x0000, 0x800c, 0x0000
        .word   0x0002, 0x0000, 0x8003, 0x0000, 0x000f, 0x0000, 0x0000, 0x0000
wait:   move.w  0x06(%a6),%d1           | VHPOSR: until the line equals d0
        lsr.w   #8,%d1
        cmp.b   %d0,%d1
        bne.s   wait
        rts
setup:  move.l  #samp,0xa0(%a6)         | ch0: 16 words, period 200, volume 64
        move.w  #16,0xa4(%a6)
        move.w  #200,0xa6(%a6)
        move.w  #64,0xa8(%a6)
        move.l  #samp,0xb0(%a6)         | ch1: 8 words, period 124, volume 32
        move.w  #8,0xb4(%a6)
        move.w  #124,0xb6(%a6)
        move.w  #32,0xb8(%a6)
        move.l  #samp,0xc0(%a6)         | ch2: 32 words, period 300, volume 64
        move.w  #32,0xc4(%a6)
        move.w  #300,0xc6(%a6)
        move.w  #64,0xc8(%a6)
        move.l  #samp,0xd0(%a6)         | ch3: 4 words, period 131, volume 40
        move.w  #4,0xd4(%a6)
        move.w  #131,0xd6(%a6)
        move.w  #40,0xd8(%a6)
        rts
        .even
samp:   .byte   0,16,32,48,64,80,96,112,127,112,96,80,64,48,32,16
        .byte   0,-16,-32,-48,-64,-80,-96,-112,-128,-112,-96,-80,-64,-48,-32,-16
        .byte   3,7,11,15,19,23,27,31,35,39,43,47,51,55,59,63
        .byte   -3,-7,-11,-15,-19,-23,-27,-31,-35,-39,-43,-47,-51,-55,-59,-63
