import sys
import re
from isa import Opcode, encode_instruction


class LispParser:
    def __init__(self, source):
        source = re.sub(r";.*", "", source)
        pattern = r'"[^"]*"|[\(\)]|[^\s\(\)]+'
        self.tokens = re.findall(pattern, source)
        self.pos = 0

    def read_from_tokens(self):
        if self.pos >= len(self.tokens):
            raise EOFError("Unexpected EOF")
        token = self.tokens[self.pos]
        self.pos += 1
        if token == "(":
            lst = []
            while self.pos < len(self.tokens) and self.tokens[self.pos] != ")":
                lst.append(self.read_from_tokens())
            if self.pos >= len(self.tokens):
                raise SyntaxError("Missing ')'")
            self.pos += 1
            return lst
        elif token == ")":
            raise SyntaxError("Unexpected ')'")
        else:
            if token.startswith('"') and token.endswith('"'):
                return {"type": "string", "value": token[1:-1].replace("\\n", "\n")}
            try:
                return int(token)
            except ValueError:
                return token

    def build_ast(self, expr):
        if isinstance(expr, int):
            return {"type": "number", "value": expr}
        if isinstance(expr, dict) and expr.get("type") == "string":
            return expr
        if isinstance(expr, str):
            return {"type": "var", "name": expr}
        if isinstance(expr, list):
            if not expr:
                return {"type": "empty_list"}
            op = expr[0]
            if op == "defvar":
                return {
                    "type": "defvar",
                    "name": expr[1],
                    "expr": self.build_ast(expr[2]),
                }
            if op == "setq":
                return {
                    "type": "setq",
                    "name": expr[1],
                    "expr": self.build_ast(expr[2]),
                }
            if op == "read_ptr":
                return {"type": "read_ptr", "addr": self.build_ast(expr[1])}
            if op == "write_ptr":
                return {
                    "type": "write_ptr",
                    "addr": self.build_ast(expr[1]),
                    "val": self.build_ast(expr[2]),
                }
            if op in ["+", "-", "*", "/", "mod", "=", "!=", "<", ">"]:
                left_ast = self.build_ast(expr[1])
                for i in range(2, len(expr)):
                    right_ast = self.build_ast(expr[i])
                    left_ast = {
                        "type": "binop",
                        "op": op,
                        "left": left_ast,
                        "right": right_ast,
                    }
                return left_ast
            if op == "if":
                return {
                    "type": "if",
                    "cond": self.build_ast(expr[1]),
                    "then": self.build_ast(expr[2]),
                    "else": self.build_ast(expr[3]) if len(expr) > 3 else None,
                }
            if op == "defun":
                return {
                    "type": "defun",
                    "name": expr[1],
                    "params": expr[2],
                    "body": [self.build_ast(s) for s in expr[3:]],
                }
            if op == "funcall":
                return {
                    "type": "funcall",
                    "name": expr[1],
                    "args": [self.build_ast(a) for a in expr[2:]],
                }
            if op == "print":
                return {"type": "print", "expr": self.build_ast(expr[1])}
            if op == "print_str":
                return {"type": "print_str", "expr": self.build_ast(expr[1])}
            if op == "print_char":
                return {"type": "print_char", "expr": self.build_ast(expr[1])}
            if op == "in":
                return {"type": "in", "port": expr[1]}
            if op == "defirq":
                return {"type": "defirq", "body": [self.build_ast(s) for s in expr[1:]]}
            raise SyntaxError(f"Unknown form: {op}")

    def parse_program(self):
        asts = []
        while self.pos < len(self.tokens):
            asts.append(self.build_ast(self.read_from_tokens()))
        return asts


class LispCompiler:
    def __init__(self):
        self.code, self.data = [], []
        self.variables, self.strings, self.functions = {}, {}, {}
        self.pending_calls = []
        self.tmp_count = 0
        self.data_base = 1024
        self.current_func = None

    def emit(self, opcode, arg=0):
        self.code.append((opcode, arg))
        return len(self.code) - 1

    def alloc_var(self, name):
        if name not in self.variables:
            self.variables[name] = self.data_base + len(self.data)
            self.data.append(0)
        return self.variables[name]

    def alloc_string(self, text):
        if text not in self.strings:
            addr = self.data_base + len(self.data)
            self.strings[text] = addr
            self.data.append(len(text))
            for char in text:
                self.data.append(ord(char))
        return self.strings[text]

    def compile_expr(self, ast, is_tail=False):
        t = ast["type"]
        if t == "empty_list":
            self.emit(Opcode.LDI, 0)
        elif t == "number":
            self.emit(Opcode.LDI, ast["value"])
        elif t == "string":
            self.emit(Opcode.LDI, self.alloc_string(ast["value"]))
        elif t == "var":
            self.emit(Opcode.LD, self.alloc_var(ast["name"]))
        elif t == "defvar":
            self.compile_expr(ast["expr"])
            self.emit(Opcode.ST, self.alloc_var(ast["name"]))
        elif t == "setq":
            self.compile_expr(ast["expr"])
            self.emit(Opcode.ST, self.alloc_var(ast["name"]))
        elif t == "read_ptr":
            self.compile_expr(ast["addr"])
            ptr = self.alloc_var(f"__ptr{self.tmp_count}")
            self.tmp_count += 1
            self.emit(Opcode.ST, ptr)
            self.emit(Opcode.LD_PTR, ptr)
        elif t == "write_ptr":
            self.compile_expr(ast["addr"])
            self.emit(Opcode.PUSH)
            self.compile_expr(ast["val"])
            val_tmp = self.alloc_var(f"__val{self.tmp_count}")
            self.tmp_count += 1
            self.emit(Opcode.ST, val_tmp)
            self.emit(Opcode.POP)
            ptr = self.alloc_var(f"__ptr{self.tmp_count}")
            self.tmp_count += 1
            self.emit(Opcode.ST, ptr)
            self.emit(Opcode.LD, val_tmp)
            self.emit(Opcode.ST_PTR, ptr)
        elif t == "binop":
            self.compile_expr(ast["left"])
            self.emit(Opcode.PUSH)
            self.compile_expr(ast["right"])
            temp_right = self.alloc_var(f"__t_right_{self.tmp_count}")
            self.tmp_count += 1
            self.emit(Opcode.ST, temp_right)
            self.emit(Opcode.POP)
            op = ast["op"]
            if op == "+":
                self.emit(Opcode.ADD, temp_right)
            elif op == "-":
                self.emit(Opcode.SUB, temp_right)
            elif op == "*":
                self.emit(Opcode.MUL, temp_right)
            elif op == "/":
                self.emit(Opcode.DIV, temp_right)
            elif op == "mod":
                self.emit(Opcode.MOD, temp_right)
            elif op in ["=", "!=", "<", ">"]:
                self.emit(Opcode.CMP, temp_right)
                jump_op = {
                    "=": Opcode.JZ,
                    "!=": Opcode.JNZ,
                    "<": Opcode.JLT,
                    ">": Opcode.JGT,
                }[op]
                idx_j = self.emit(jump_op, 0)
                self.emit(Opcode.LDI, 0)
                idx_end = self.emit(Opcode.JMP, 0)
                self.code[idx_j] = (jump_op, len(self.code))
                self.emit(Opcode.LDI, 1)
                self.code[idx_end] = (Opcode.JMP, len(self.code))
        elif t == "if":
            self.compile_expr(ast["cond"])
            self.emit(Opcode.CMP, self.alloc_var("__zero"))
            idx_jz = self.emit(Opcode.JZ, 0)
            self.compile_expr(ast["then"], is_tail=is_tail)
            idx_jmp = self.emit(Opcode.JMP, 0)
            self.code[idx_jz] = (Opcode.JZ, len(self.code))
            if ast["else"]:
                self.compile_expr(ast["else"], is_tail=is_tail)
            self.code[idx_jmp] = (Opcode.JMP, len(self.code))
        elif t == "defun":
            self.current_func = ast["name"]
            self.functions[ast["name"]]["addr"] = len(self.code)
            for i, stmt in enumerate(ast["body"]):
                self.compile_expr(stmt, is_tail=(i == len(ast["body"]) - 1))
            self.emit(Opcode.RET)
            self.current_func = None
        elif t == "funcall":
            fname = ast["name"]
            target_params = (
                self.functions[fname]["params"] if fname in self.functions else []
            )
            t_args = []
            for arg in ast["args"]:
                self.compile_expr(arg)
                t_var = self.alloc_var(f"__arg{self.tmp_count}")
                self.tmp_count += 1
                self.emit(Opcode.ST, t_var)
                t_args.append(t_var)
            if is_tail and fname == self.current_func:
                for t_var, p in zip(t_args, target_params):
                    self.emit(Opcode.LD, t_var)
                    self.emit(Opcode.ST, self.alloc_var(p))
                self.emit(Opcode.JMP, self.functions[fname]["addr"])
            else:
                for p in target_params:
                    self.emit(Opcode.LD, self.alloc_var(p))
                    self.emit(Opcode.PUSH)
                for t_var, p in zip(t_args, target_params):
                    self.emit(Opcode.LD, t_var)
                    self.emit(Opcode.ST, self.alloc_var(p))
                if (
                    fname in self.functions
                    and self.functions[fname]["addr"] is not None
                ):
                    self.emit(Opcode.CALL, self.functions[fname]["addr"])
                else:
                    idx = self.emit(Opcode.CALL, 0)
                    self.pending_calls.append((idx, fname))
                ret_val = self.alloc_var(f"__ret{self.tmp_count}")
                self.tmp_count += 1
                self.emit(Opcode.ST, ret_val)
                for p in reversed(target_params):
                    self.emit(Opcode.POP)
                    self.emit(Opcode.ST, self.alloc_var(p))
                self.emit(Opcode.LD, ret_val)
        elif t == "print":
            self.compile_expr(ast["expr"])
            self.emit(Opcode.OUT, 1)
        elif t == "print_char":
            self.compile_expr(ast["expr"])
            self.emit(Opcode.OUT, 3)
        elif t == "print_str":
            self.compile_expr(ast["expr"])
            ptr = self.alloc_var(f"__s_p_{self.tmp_count}")
            length = self.alloc_var(f"__s_l_{self.tmp_count}")
            idx = self.alloc_var(f"__s_i_{self.tmp_count}")
            t_cmp = self.alloc_var(f"__s_c_{self.tmp_count}")
            t_add = self.alloc_var(f"__s_a_{self.tmp_count}")
            t_inc = self.alloc_var(f"__s_in_{self.tmp_count}")
            t_addr = self.alloc_var(f"__s_ad_{self.tmp_count}")
            self.tmp_count += 1

            self.emit(Opcode.ST, ptr)
            self.emit(Opcode.LD_PTR, ptr)
            self.emit(Opcode.ST, length)
            self.emit(Opcode.LDI, 1)
            self.emit(Opcode.ST, idx)
            loop_start = len(self.code)
            self.emit(Opcode.LD, idx)
            self.emit(Opcode.PUSH)
            self.emit(Opcode.LD, length)
            self.emit(Opcode.ST, t_cmp)
            self.emit(Opcode.POP)
            self.emit(Opcode.CMP, t_cmp)
            idx_jgt = self.emit(Opcode.JGT, 0)

            self.emit(Opcode.LD, ptr)
            self.emit(Opcode.PUSH)
            self.emit(Opcode.LD, idx)
            self.emit(Opcode.ST, t_add)
            self.emit(Opcode.POP)
            self.emit(Opcode.ADD, t_add)
            self.emit(Opcode.ST, t_addr)

            self.emit(Opcode.LD_PTR, t_addr)
            self.emit(Opcode.OUT, 3)

            self.emit(Opcode.LD, idx)
            self.emit(Opcode.PUSH)
            self.emit(Opcode.LDI, 1)
            self.emit(Opcode.ST, t_inc)
            self.emit(Opcode.POP)
            self.emit(Opcode.ADD, t_inc)
            self.emit(Opcode.ST, idx)
            self.emit(Opcode.JMP, loop_start)

            self.code[idx_jgt] = (Opcode.JGT, len(self.code))

            self.emit(Opcode.LDI, 1)

        elif t == "in":
            self.emit(Opcode.IN, ast["port"])
        elif t == "defirq":
            self.functions["isr"]["addr"] = len(self.code)
            for stmt in ast["body"]:
                self.compile_expr(stmt)
            self.emit(Opcode.IRET)

    def compile(self, asts):
        self.emit(Opcode.JMP, 3)
        self.pending_calls.append((1, "isr"))
        self.emit(Opcode.JMP, 0)
        self.emit(Opcode.NOP)
        has_isr = any(ast["type"] == "defirq" for ast in asts)
        for ast in asts:
            if ast["type"] in ["defun", "defirq"]:
                self.functions[ast.get("name", "isr")] = {
                    "params": ast.get("params", []),
                    "addr": None,
                }
        for ast in asts:
            if ast["type"] not in ["defun", "defirq"]:
                self.compile_expr(ast)
        self.emit(Opcode.HLT)
        if not has_isr:
            self.functions["isr"] = {"params": [], "addr": len(self.code)}
            self.emit(Opcode.IRET)
        for ast in asts:
            if ast["type"] in ["defun", "defirq"]:
                self.compile_expr(ast)
        for idx, fname in self.pending_calls:
            if fname in self.functions:
                self.code[idx] = (self.code[idx][0], self.functions[fname]["addr"])

        binary = bytearray()
        debug_text = ""
        for i, (op, arg) in enumerate(self.code):
            encoded = encode_instruction(op, arg)
            binary.extend(encoded)
            debug_text += f"{i:04} - {encoded.hex().upper()} - {op.name} {arg}\n"
        while len(binary) // 4 < self.data_base:
            binary.extend(encode_instruction(Opcode.NOP, 0))
        for d in self.data:
            binary.extend(d.to_bytes(4, byteorder="little", signed=True))
        return binary, debug_text


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as src_file:
        source = src_file.read()
    binary, debug = LispCompiler().compile(LispParser(source).parse_program())
    with open(sys.argv[2], "wb") as bin_file:
        bin_file.write(binary)
    if len(sys.argv) == 4:
        with open(sys.argv[3], "w", encoding="utf-8") as dbg_file:
            dbg_file.write(debug)
