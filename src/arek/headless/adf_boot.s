| arek adf build: the boot block's code (offset 12 of the disk). Entered by the Kickstart's strap with
| a1 = the trackdisk IORequest (open), a6 = ExecBase. Reads LEN bytes from disk offset 1024 into a temporary
| chip RAM buffer, takes the machine over, moves the image to LOAD and jumps to ENTRY with a7 = STACK.
        .text
boot:   movea.l %a1,%a4                 | the IORequest
        move.l  len(%pc),%d0
        moveq   #2,%d1                  | MEMF_CHIP
        jsr     -198(%a6)               | AllocMem
        tst.l   %d0
        beq.s   fail
        movea.l %d0,%a3                 | the temporary buffer
        movea.l %a4,%a1
        move.w  #2,28(%a1)              | io_Command = CMD_READ
        move.l  len(%pc),36(%a1)        | io_Length
        move.l  %a3,40(%a1)             | io_Data
        move.l  #1024,44(%a1)           | io_Offset: behind the boot block
        jsr     -456(%a6)               | DoIO
        tst.l   %d0
        bne.s   fail
        movea.l %a4,%a1
        move.w  #9,28(%a1)              | TD_MOTOR
        clr.l   36(%a1)                 | off
        jsr     -456(%a6)
        lea     super(%pc),%a5
        jsr     -30(%a6)                | Supervisor(): super runs in supervisor mode
fail:   move.w  #0x0f00,0xdff180        | no memory or a read error: a red screen
        bra.s   fail
super:  move.w  #0x2700,%sr
        lea     0xdff000,%a6
        move.w  #0x7fff,0x9a(%a6)       | INTENA
        move.w  #0x7fff,0x9c(%a6)       | INTREQ
        move.w  #0x7fff,0x96(%a6)       | DMACON
        lea     mover(%pc),%a0          | the mover to $100: outside the image and the buffer
        lea     0x100.w,%a1
        moveq   #(mover_end-mover)/2-1,%d0
1:      move.w  (%a0)+,(%a1)+
        dbf     %d0,1b
        movea.l %a3,%a0                 | from
        movea.l load(%pc),%a1           | to
        move.l  len(%pc),%d0            | bytes, a multiple of 512
        movea.l stack(%pc),%a7
        movea.l entry(%pc),%a2
        jmp     0x100.w
mover:  cmpa.l  %a0,%a1
        bls.s   up                      | the image lies at or below the buffer: upwards
        adda.l  %d0,%a0
        adda.l  %d0,%a1
        lsr.l   #2,%d0
dn:     move.l  -(%a0),-(%a1)
        subq.l  #1,%d0
        bne.s   dn
        jmp     (%a2)
up:     lsr.l   #2,%d0
u2:     move.l  (%a0)+,(%a1)+
        subq.l  #1,%d0
        bne.s   u2
        jmp     (%a2)
mover_end:
        .even
len:    .long   0
load:   .long   0
entry:  .long   0
stack:  .long   0
