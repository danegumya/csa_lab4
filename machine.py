import sys
import json
from isa import Opcode, decode_instruction


def to_signed32(x):
    x &= 0xFFFFFFFF
    return x if x < 0x80000000 else x - 0x100000000


class DataPath:
    def __init__(self, memory_size=16384):
        self.memory = [0] * memory_size
        self.acc = 0
        self.shadow_acc = 0
        self.shadow_addr = None
        self.shadow_active = False
        self.zero_flag = False
        self.negative_flag = False
        self.sp = memory_size - 1

    def flush_shadow(self):
        if self.shadow_active:
            self.memory[self.shadow_addr] = self.shadow_acc
            self.shadow_active = False
            return True
        return False


class ControlUnit:
    def __init__(self, datapath, schedule):
        self.dp = datapath
        self.ip = 0
        self.ticks = 0
        self.schedule = schedule
        self.port_data = None
        self.irq_line = False
        self.output_buffer = []
        self.interrupt_enabled = True
        self.halted = False

    def check_interrupts(self):
        while self.schedule and self.schedule[0][0] <= self.ticks:
            _, char = self.schedule.pop(0)
            self.port_data = char
            self.irq_line = True

        if self.irq_line and self.interrupt_enabled:
            if self.dp.shadow_active:
                self.dp.flush_shadow()
                self.ticks += 1

            self.interrupt_enabled = False
            self.irq_line = False

            self.dp.memory[self.dp.sp] = self.ip
            self.dp.sp -= 1
            self.dp.memory[self.dp.sp] = self.dp.acc
            self.dp.sp -= 1
            flags = (int(self.dp.zero_flag) << 1) | int(self.dp.negative_flag)
            self.dp.memory[self.dp.sp] = flags
            self.dp.sp -= 1

            self.ip = 1
            self.ticks += 4
            return True
        return False

    def tick(self):
        if self.halted:
            return
        if self.check_interrupts():
            return

        raw_instr = self.dp.memory[self.ip]
        if isinstance(raw_instr, int):
            raw_instr = raw_instr.to_bytes(4, byteorder="little", signed=True)

        opcode, arg = decode_instruction(raw_instr)

        current_ip = self.ip
        self.ip += 1
        self.ticks += 1

        parallel_flush = False

        if opcode in [Opcode.ST, Opcode.ST_PTR]:
            if self.dp.shadow_active:
                self.dp.flush_shadow()
                self.ticks += 1

            if opcode == Opcode.ST_PTR:
                target_addr = self.dp.memory[arg]
                self.ticks += 1
            else:
                target_addr = arg

            self.dp.shadow_acc = self.dp.acc
            self.dp.shadow_addr = target_addr
            self.dp.shadow_active = True

            isr_marker = "[ISR] " if not self.interrupt_enabled else ""
            log_msg = f"Tick {self.ticks:4} | {isr_marker}IP {current_ip:04} | {opcode.name:6} {arg} | Deferred Store"
            print(log_msg)
            return

        if self.dp.shadow_active and opcode in [
            Opcode.LD,
            Opcode.LDI,
            Opcode.LD_PTR,
            Opcode.ADD,
            Opcode.SUB,
            Opcode.MUL,
            Opcode.DIV,
            Opcode.MOD,
            Opcode.CMP,
        ]:
            self.dp.flush_shadow()
            parallel_flush = True

        if self.dp.shadow_active and opcode in [
            Opcode.IN,
            Opcode.OUT,
            Opcode.JMP,
            Opcode.JZ,
            Opcode.JNZ,
            Opcode.JLT,
            Opcode.JGT,
            Opcode.CALL,
        ]:
            self.dp.flush_shadow()
            self.ticks += 1

        if opcode == Opcode.LD:
            self.dp.acc = self.dp.memory[arg]
        elif opcode == Opcode.LD_PTR:
            ptr_address = self.dp.memory[arg]
            self.ticks += 1
            self.dp.acc = self.dp.memory[ptr_address]
        elif opcode == Opcode.LDI:
            self.dp.acc = arg
        elif opcode == Opcode.ADD:
            self.dp.acc = to_signed32(self.dp.acc + self.dp.memory[arg])
        elif opcode == Opcode.SUB:
            self.dp.acc = to_signed32(self.dp.acc - self.dp.memory[arg])
        elif opcode == Opcode.MUL:
            self.dp.acc = to_signed32(self.dp.acc * self.dp.memory[arg])
        elif opcode == Opcode.DIV:
            self.dp.acc = to_signed32(self.dp.acc // self.dp.memory[arg])
        elif opcode == Opcode.MOD:
            self.dp.acc = to_signed32(self.dp.acc % self.dp.memory[arg])
        elif opcode == Opcode.CMP:
            self.dp.zero_flag = self.dp.acc == self.dp.memory[arg]
            self.dp.negative_flag = self.dp.acc < self.dp.memory[arg]
        elif opcode == Opcode.JMP:
            self.ip = arg
        elif opcode == Opcode.JZ:
            if self.dp.zero_flag:
                self.ip = arg
        elif opcode == Opcode.JNZ:
            if not self.dp.zero_flag:
                self.ip = arg
        elif opcode == Opcode.JLT:
            if self.dp.negative_flag:
                self.ip = arg
        elif opcode == Opcode.JGT:
            if not self.dp.zero_flag and not self.dp.negative_flag:
                self.ip = arg
        elif opcode == Opcode.IN:
            if arg == 1:
                self.dp.acc = ord(self.port_data) if self.port_data else 0
                self.port_data = None
        elif opcode == Opcode.OUT:
            if arg == 1:
                self.output_buffer.append(str(self.dp.acc))
            elif arg == 2:
                addr = self.dp.acc
                length = self.dp.memory[addr]
                chars = [chr(self.dp.memory[addr + 1 + i]) for i in range(length)]
                self.output_buffer.append("".join(chars))
            elif arg == 3:
                self.output_buffer.append(chr(self.dp.acc & 0xFF))
        elif opcode == Opcode.PUSH:
            self.dp.memory[self.dp.sp] = self.dp.acc
            self.dp.sp -= 1
        elif opcode == Opcode.POP:
            self.dp.sp += 1
            self.dp.acc = self.dp.memory[self.dp.sp]
        elif opcode == Opcode.CALL:
            self.dp.memory[self.dp.sp] = self.ip
            self.dp.sp -= 1
            self.ip = arg
        elif opcode == Opcode.RET:
            self.dp.sp += 1
            self.ip = self.dp.memory[self.dp.sp]
        elif opcode == Opcode.IRET:
            self.dp.sp += 1
            flags = self.dp.memory[self.dp.sp]
            self.dp.zero_flag = bool(flags & 2)
            self.dp.negative_flag = bool(flags & 1)
            self.dp.sp += 1
            self.dp.acc = self.dp.memory[self.dp.sp]
            self.dp.sp += 1
            self.ip = self.dp.memory[self.dp.sp]
            self.interrupt_enabled = True
        elif opcode == Opcode.HLT:
            self.dp.flush_shadow()
            self.halted = True

        isr_marker = "[ISR] " if not self.interrupt_enabled else ""
        log_msg = f"Tick {self.ticks:4} | {isr_marker}IP {current_ip:04} | {opcode.name:6} {arg} | ACC={self.dp.acc}"
        if parallel_flush:
            log_msg += " | [Parallel Flush]"
        print(log_msg)


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
    while not cu.halted and cu.ticks < 5000000:
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
