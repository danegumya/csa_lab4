import sys
import json
from enum import Enum
from isa import Opcode, decode_instruction


def to_signed32(x):
    x &= 0xFFFFFFFF
    return x if x < 0x80000000 else x - 0x100000000


class State(Enum):
    FETCH = "FETCH"
    EXECUTE = "EXECUTE"
    EXECUTE_PTR_READ = "EXECUTE_PTR_READ"
    EXECUTE_PTR_FINISH = "EXECUTE_PTR_FINISH"
    EXECUTE_IRET_FLAGS = "EXECUTE_IRET_FLAGS"
    EXECUTE_IRET_ACC = "EXECUTE_IRET_ACC"
    EXECUTE_IRET_IP = "EXECUTE_IRET_IP"
    FLUSH_STALL = "FLUSH_STALL"
    TRAP_1 = "TRAP_1"
    TRAP_2 = "TRAP_2"
    TRAP_3 = "TRAP_3"
    TRAP_4 = "TRAP_4"
    HALTED = "HALTED"


class DataPath:
    def __init__(self, memory_size=16384):
        self.memory = [0] * memory_size
        self.acc = 0
        self.shadow_acc = 0
        self.shadow_addr = 0
        self.shadow_active = False
        self.zero_flag = False
        self.negative_flag = False
        self.sp = memory_size - 1
        self.temp_ptr = 0


class ControlUnit:
    def __init__(self, datapath, schedule):
        self.dp = datapath
        self.ticks = 0
        self.schedule = schedule
        self.ip = 0
        self.current_ip = 0
        self.ir = 0
        self.opcode = Opcode.NOP
        self.arg = 0
        self.state = State.FETCH
        self.next_state = State.FETCH
        self.port_buffer = []
        self.irq_line = False
        self.interrupt_enabled = True
        self.just_returned_from_interrupt = False
        self.output_buffer = []

    def check_external_devices(self):
        while self.schedule and self.schedule[0][0] <= self.ticks:
            _, char = self.schedule.pop(0)
            self.port_buffer.append(char)
        self.irq_line = bool(self.port_buffer)

    def log_execute(self, parallel_flush_msg=""):
        isr = "[ISR] " if not self.interrupt_enabled else ""
        if self.opcode in [Opcode.ST, Opcode.ST_PTR]:
            log_msg = f"Tick {self.ticks:4} | {isr}IP {self.current_ip:04} | {self.opcode.name:6} {self.arg} | Deferred Store"
        else:
            log_msg = f"Tick {self.ticks:4} | {isr}IP {self.current_ip:04} | {self.opcode.name:6} {self.arg} | ACC={self.dp.acc}"
        if parallel_flush_msg:
            log_msg += parallel_flush_msg
        print(log_msg)

    def tick(self):
        self.ticks += 1
        self.check_external_devices()

        if self.state == State.HALTED:
            return

        if self.state == State.FETCH:
            isr = "[ISR] " if not self.interrupt_enabled else ""
            print(f"Tick {self.ticks:4} | {isr}IP {self.ip:04} | FETCH")

            can_interrupt = (
                self.irq_line
                and self.interrupt_enabled
                and not self.just_returned_from_interrupt
            )
            if can_interrupt:
                if self.dp.shadow_active:
                    self.state = State.FLUSH_STALL
                    self.next_state = State.TRAP_1
                else:
                    self.state = State.TRAP_1
                return

            self.just_returned_from_interrupt = False
            self.current_ip = self.ip
            raw_instr = self.dp.memory[self.ip]
            if isinstance(raw_instr, int):
                raw_instr = raw_instr.to_bytes(4, byteorder="little", signed=True)
            self.opcode, self.arg = decode_instruction(raw_instr)
            self.ip += 1

            if self.opcode in [Opcode.LD_PTR, Opcode.ST_PTR]:
                self.state = State.EXECUTE_PTR_READ
            elif self.opcode == Opcode.IRET:
                self.state = State.EXECUTE_IRET_FLAGS
            else:
                self.state = State.EXECUTE
            return

        elif self.state == State.EXECUTE:
            parallel_flush_msg = ""
            op = self.opcode
            arg = self.arg

            if self.dp.shadow_active:
                if op in [
                    Opcode.ST,
                    Opcode.JMP,
                    Opcode.JZ,
                    Opcode.JNZ,
                    Opcode.JLT,
                    Opcode.JGT,
                    Opcode.CALL,
                    Opcode.IN,
                    Opcode.OUT,
                    Opcode.RET,
                ]:
                    isr = "[ISR] " if not self.interrupt_enabled else ""
                    print(
                        f"Tick {self.ticks:4} | {isr}IP {self.current_ip:04} | STALL (Hazard Unit Flush)"
                    )
                    self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                    self.dp.shadow_active = False
                    return
                else:
                    self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                    self.dp.shadow_active = False
                    parallel_flush_msg = " | [Parallel Flush]"

            if op == Opcode.LD:
                self.dp.acc = self.dp.memory[arg]
            elif op == Opcode.LDI:
                self.dp.acc = arg
            elif op == Opcode.ADD:
                self.dp.acc = to_signed32(self.dp.acc + self.dp.memory[arg])
            elif op == Opcode.SUB:
                self.dp.acc = to_signed32(self.dp.acc - self.dp.memory[arg])
            elif op == Opcode.MUL:
                self.dp.acc = to_signed32(self.dp.acc * self.dp.memory[arg])
            elif op == Opcode.DIV:
                self.dp.acc = to_signed32(self.dp.acc // self.dp.memory[arg])
            elif op == Opcode.MOD:
                self.dp.acc = to_signed32(self.dp.acc % self.dp.memory[arg])
            elif op == Opcode.CMP:
                self.dp.zero_flag = self.dp.acc == self.dp.memory[arg]
                self.dp.negative_flag = self.dp.acc < self.dp.memory[arg]
            elif op == Opcode.ST:
                self.dp.shadow_acc = self.dp.acc
                self.dp.shadow_addr = arg
                self.dp.shadow_active = True
            elif op == Opcode.JMP:
                self.ip = arg
            elif op == Opcode.JZ:
                if self.dp.zero_flag:
                    self.ip = arg
            elif op == Opcode.JNZ:
                if not self.dp.zero_flag:
                    self.ip = arg
            elif op == Opcode.JLT:
                if self.dp.negative_flag:
                    self.ip = arg
            elif op == Opcode.JGT:
                if not self.dp.zero_flag and not self.dp.negative_flag:
                    self.ip = arg
            elif op == Opcode.IN:
                if arg == 1:
                    if self.port_buffer:
                        c = self.port_buffer.pop(0)
                        if isinstance(c, int):
                            self.dp.acc = c
                        elif c == "":
                            self.dp.acc = 0
                        else:
                            self.dp.acc = ord(c)
                    else:
                        self.dp.acc = 0
            elif op == Opcode.OUT:
                if arg == 1:
                    self.output_buffer.append(str(self.dp.acc))
                elif arg == 3:
                    self.output_buffer.append(chr(self.dp.acc & 0xFF))
            elif op == Opcode.PUSH:
                self.dp.memory[self.dp.sp] = self.dp.acc
                self.dp.sp -= 1
            elif op == Opcode.POP:
                self.dp.sp += 1
                self.dp.acc = self.dp.memory[self.dp.sp]
            elif op == Opcode.CALL:
                self.dp.memory[self.dp.sp] = self.ip
                self.dp.sp -= 1
                self.ip = arg
            elif op == Opcode.RET:
                self.dp.sp += 1
                self.ip = self.dp.memory[self.dp.sp]
            elif op == Opcode.HLT:
                self.state = State.HALTED
                if self.dp.shadow_active:
                    self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                    self.dp.shadow_active = False

            self.log_execute(parallel_flush_msg)
            if self.state != State.HALTED:
                self.state = State.FETCH

        elif self.state == State.EXECUTE_PTR_READ:
            if self.dp.shadow_active:
                isr = "[ISR] " if not self.interrupt_enabled else ""
                print(
                    f"Tick {self.ticks:4} | {isr}IP {self.current_ip:04} | STALL (Hazard Unit Flush)"
                )
                self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                self.dp.shadow_active = False
                return
            self.dp.temp_ptr = self.dp.memory[self.arg]
            isr = "[ISR] " if not self.interrupt_enabled else ""
            print(
                f"Tick {self.ticks:4} | {isr}IP {self.current_ip:04} | {self.opcode.name:6} {self.arg} | Ptr Read"
            )
            self.state = State.EXECUTE_PTR_FINISH

        elif self.state == State.EXECUTE_PTR_FINISH:
            if self.opcode == Opcode.LD_PTR:
                self.dp.acc = self.dp.memory[self.dp.temp_ptr]
            elif self.opcode == Opcode.ST_PTR:
                self.dp.shadow_acc = self.dp.acc
                self.dp.shadow_addr = self.dp.temp_ptr
                self.dp.shadow_active = True
            self.log_execute()
            self.state = State.FETCH

        elif self.state == State.EXECUTE_IRET_FLAGS:
            if self.dp.shadow_active:
                print(
                    f"Tick {self.ticks:4} | [ISR] IP {self.current_ip:04} | STALL (Hazard Unit Flush)"
                )
                self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                self.dp.shadow_active = False
                return
            self.dp.sp += 1
            flags = self.dp.memory[self.dp.sp]
            self.dp.zero_flag = bool(flags & 2)
            self.dp.negative_flag = bool(flags & 1)
            print(
                f"Tick {self.ticks:4} | [ISR] IP {self.current_ip:04} | IRET   0 | Pop Flags"
            )
            self.state = State.EXECUTE_IRET_ACC

        elif self.state == State.EXECUTE_IRET_ACC:
            self.dp.sp += 1
            self.dp.acc = self.dp.memory[self.dp.sp]
            print(
                f"Tick {self.ticks:4} | [ISR] IP {self.current_ip:04} | IRET   0 | Pop ACC"
            )
            self.state = State.EXECUTE_IRET_IP

        elif self.state == State.EXECUTE_IRET_IP:
            self.dp.sp += 1
            self.ip = self.dp.memory[self.dp.sp]
            self.interrupt_enabled = True
            self.just_returned_from_interrupt = True
            print(
                f"Tick {self.ticks:4} | [ISR] IP {self.current_ip:04} | IRET   0 | Pop IP"
            )
            self.state = State.FETCH

        elif self.state == State.FLUSH_STALL:
            isr = "[ISR] " if not self.interrupt_enabled else ""
            print(
                f"Tick {self.ticks:4} | {isr}IP {self.current_ip:04} | STALL (Hazard Unit Flush)"
            )
            self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
            self.dp.shadow_active = False
            self.state = self.next_state

        elif self.state == State.TRAP_1:
            self.dp.memory[self.dp.sp] = self.ip
            self.dp.sp -= 1
            self.state = State.TRAP_2
            print(f"Tick {self.ticks:4} | [ISR] Hardware Trap: Push IP")

        elif self.state == State.TRAP_2:
            self.dp.memory[self.dp.sp] = self.dp.acc
            self.dp.sp -= 1
            self.state = State.TRAP_3
            print(f"Tick {self.ticks:4} | [ISR] Hardware Trap: Push ACC")

        elif self.state == State.TRAP_3:
            flags = (int(self.dp.zero_flag) << 1) | int(self.dp.negative_flag)
            self.dp.memory[self.dp.sp] = flags
            self.dp.sp -= 1
            self.state = State.TRAP_4
            print(f"Tick {self.ticks:4} | [ISR] Hardware Trap: Push Flags")

        elif self.state == State.TRAP_4:
            self.interrupt_enabled = False
            self.ip = 1
            self.state = State.FETCH
            print(f"Tick {self.ticks:4} | [ISR] Hardware Trap: JMP Vector")


def simulate(binary_data, schedule):
    dp = DataPath()
    for i in range(0, len(binary_data), 4):
        if i // 4 >= len(dp.memory):
            break
        word = binary_data[i : i + 4]
        dp.memory[i // 4] = word
        if (i // 4) >= 1024:
            dp.memory[i // 4] = int.from_bytes(word, byteorder="little", signed=True)
    cu = ControlUnit(dp, schedule)
    print("--- Simulation Trace ---")
    while cu.state != State.HALTED and cu.ticks < 10000000:
        cu.tick()
    print("--- Output ---")
    out_text = "".join(cu.output_buffer)
    print(out_text)
    return out_text


if __name__ == "__main__":
    with open(sys.argv[1], "rb") as bin_file:
        binary = bin_file.read()
    with open(sys.argv[2], "r", encoding="utf-8") as sched_file:
        schedule = json.load(sched_file)
    simulate(binary, schedule)
