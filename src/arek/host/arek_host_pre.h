/* arek_host_pre.h - the macros a host defines before it includes the translation (arek recomp --timing --bus-table):
 * every instruction goes to tick_hook (TICK_HOOK), every bus access to the bus model (BUS_HOOK), unmodelled custom
 * registers and every register write to the host (HW_HOOK), the CIAs to the host (CIA_HOOK); the glue's own tick_hook
 * is replaced by the host's (AREK_GLUE_NO_TICK); the driver's main is renamed so the host has its own. */
#ifndef AREK_HOST_PRE_H
#define AREK_HOST_PRE_H
#define TICK_HOOK 1
#define BUS_HOOK 1
#define HW_HOOK 1
#define CIA_HOOK 1
#define AREK_GLUE_NO_TICK 1
#define main recomp_main
#endif
