import sys
import json
from enum import Enum
from isa import Opcode, decode_instruction


def to_signed32(x):
    x &= 0xFFFFFFFF
    return x if x < 0x80000000 else x - 0x100000000


# Состояния Конечного Автомата (FSM)
class State(Enum):
    FETCH = "FETCH"
    EXECUTE = "EXECUTE"
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
        self.delay_ticks = 0

        # Аппаратный FIFO буфер для порта
        self.port_buffer = []
        self.irq_line = False
        self.interrupt_enabled = True
        self.output_buffer = []

    def check_external_devices(self):
        # Если пришло время по расписанию - кладем символ в аппаратный буфер
        while self.schedule and self.schedule[0][0] <= self.ticks:
            _, char = self.schedule.pop(0)
            self.port_buffer.append(char)
            self.irq_line = True  # Edge-triggered прерывание

    def tick(self):
        self.ticks += 1
        self.check_external_devices()

        if self.state == State.HALTED:
            return

        # ==================================
        # ФАЗА ВЫБОРКИ КОМАНДЫ И ПРЕРЫВАНИЙ
        # ==================================
        if self.state == State.FETCH:
            # 1. ПЕРЕХВАТ (TRAP)
            if self.irq_line and self.interrupt_enabled:
                if self.dp.shadow_active:
                    self.state = State.FLUSH_STALL
                    self.next_state = State.TRAP_1
                else:
                    self.state = State.TRAP_1
                return

            # 2. НОРМАЛЬНАЯ ВЫБОРКА
            self.current_ip = self.ip
            raw_instr = self.dp.memory[self.ip]

            if isinstance(raw_instr, int):
                raw_instr = raw_instr.to_bytes(4, byteorder="little", signed=True)

            self.opcode, self.arg = decode_instruction(raw_instr)

            self.ip += 1
            self.state = State.EXECUTE
            self.delay_ticks = 0
            return

        # ==================================
        # ФАЗА ИСПОЛНЕНИЯ
        # ==================================
        elif self.state == State.EXECUTE:
            parallel_flush_msg = ""

            if self.dp.shadow_active:
                if self.opcode in [
                    Opcode.ST,
                    Opcode.ST_PTR,
                    Opcode.JMP,
                    Opcode.JZ,
                    Opcode.JNZ,
                    Opcode.JLT,
                    Opcode.JGT,
                    Opcode.CALL,
                    Opcode.IN,
                    Opcode.OUT,
                    Opcode.RET,
                    Opcode.IRET,
                ]:
                    self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                    self.dp.shadow_active = False
                    return
                else:
                    self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                    self.dp.shadow_active = False
                    parallel_flush_msg = " | [Parallel Flush]"

            op = self.opcode
            arg = self.arg

            if op in [Opcode.LD_PTR, Opcode.ST_PTR]:
                if self.delay_ticks < 1:
                    self.delay_ticks += 1
                    return
            elif op == Opcode.IRET:
                if self.delay_ticks < 2:
                    self.delay_ticks += 1
                    return

            if op == Opcode.LD:
                self.dp.acc = self.dp.memory[arg]
            elif op == Opcode.LD_PTR:
                ptr_address = self.dp.memory[arg]
                self.dp.acc = self.dp.memory[ptr_address]
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
            elif op == Opcode.ST_PTR:
                ptr_address = self.dp.memory[arg]
                self.dp.shadow_acc = self.dp.acc
                self.dp.shadow_addr = ptr_address
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
                    # Читаем из очереди (FIFO)
                    if self.port_buffer:
                        self.dp.acc = ord(self.port_buffer.pop(0))
                    else:
                        self.dp.acc = 0
            elif op == Opcode.OUT:
                if arg == 1:
                    self.output_buffer.append(str(self.dp.acc))
                elif arg == 2:
                    addr = self.dp.acc
                    length = self.dp.memory[addr]
                    chars = [chr(self.dp.memory[addr + 1 + i]) for i in range(length)]
                    self.output_buffer.append("".join(chars))
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
            elif op == Opcode.IRET:
                self.dp.sp += 1
                flags = self.dp.memory[self.dp.sp]
                self.dp.zero_flag = bool(flags & 2)
                self.dp.negative_flag = bool(flags & 1)
                self.dp.sp += 1
                self.dp.acc = self.dp.memory[self.dp.sp]
                self.dp.sp += 1
                self.ip = self.dp.memory[self.dp.sp]
                self.interrupt_enabled = True
            elif op == Opcode.HLT:
                self.state = State.HALTED
                if self.dp.shadow_active:
                    self.dp.memory[self.dp.shadow_addr] = self.dp.shadow_acc
                    self.dp.shadow_active = False

            isr_marker = "[ISR] " if not self.interrupt_enabled else ""
            if op in [Opcode.ST, Opcode.ST_PTR]:
                log_msg = f"Tick {self.ticks:4} | {isr_marker}IP {self.current_ip:04} | {op.name:6} {arg} | Deferred Store"
            else:
                log_msg = f"Tick {self.ticks:4} | {isr_marker}IP {self.current_ip:04} | {op.name:6} {arg} | ACC={self.dp.acc}"

            if parallel_flush_msg:
                log_msg += parallel_flush_msg

            print(log_msg)

            if self.state != State.HALTED:
                self.state = State.FETCH

        # ==================================
        # СТАТУСЫ АППАРАТНЫХ ЗАДЕРЖЕК
        # ==================================
        elif self.state == State.FLUSH_STALL:
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
            self.irq_line = False  # Сбрасываем сигнал прерывания
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
