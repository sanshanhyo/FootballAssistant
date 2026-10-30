// Independent test fixture mirroring the verified nine-instruction shape.
// Its data slot and functions belong only to the test executable.
.section __TEXT,__text,regular,pure_instructions
.p2align 2
.globl _fa_fixture_set_callback
_fa_fixture_set_callback:
  adrp x8, _fa_fixture_callback_slot@PAGE
  str x0, [x8, _fa_fixture_callback_slot@PAGEOFF]
  ret

.p2align 2
.globl _fa_fixture_dispatch
_fa_fixture_dispatch:
  adrp x8, _fa_fixture_callback_slot@PAGE
  ldr x6, [x8, _fa_fixture_callback_slot@PAGEOFF]
  ldp x8, x9, [x0, #0x10]
  ldp x10, x3, [x1]
  ldp x4, x5, [x2]
  mov x0, x8
  mov x1, x9
  mov x2, x10
  br x6

.section __DATA,__data
.p2align 3
_fa_fixture_callback_slot:
  .quad 0
