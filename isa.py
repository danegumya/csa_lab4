from enum import Enum


class Opcode(Enum):
    NOP = 0
    LD = 1  # ACC = Mem[arg]
    LDI = 2  # ACC = arg
    ST = 3  # Mem[arg] = ACC (отложено)
    ADD = 4  # ACC = ACC + Mem[arg]
    SUB = 5  # ACC = ACC - Mem[arg]
    MOD = 6  # ACC = ACC % Mem[arg]
    CMP = 7  # Сравнить ACC с Mem[arg], установить флаги Z, N
    JMP = 8  # Безусловный переход
    JZ = 9  # Переход если Zero (==)
    JNZ = 10  # Переход если не Zero (!=)
    IN = 11  # Ввод из порта
    OUT = 12  # Вывод в порт
    PUSH = 13  # SP--, Mem[SP] = ACC
    POP = 14  # ACC = Mem[SP], SP++
    CALL = 15  # SP--, Mem[SP] = IP, IP = arg
    RET = 16  # IP = Mem[SP], SP++
    IRET = 17  # Возврат из прерывания
    HLT = 18  # Остановка

    LD_PTR = 19  # ACC = Mem[Mem[arg]]
    ST_PTR = 20  # Mem[Mem[arg]] = ACC
    JLT = 21  # Переход если ACC < Mem
    JGT = 22  # Переход если ACC > Mem
    MUL = 23
    DIV = 24


def encode_instruction(opcode: Opcode, arg: int = 0) -> bytes:
    arg_bytes = arg.to_bytes(3, byteorder="little", signed=True)
    return bytes([opcode.value]) + arg_bytes


def decode_instruction(data: bytes):
    opcode = Opcode(data[0])
    arg = int.from_bytes(data[1:4], byteorder="little", signed=True)
    return opcode, arg
