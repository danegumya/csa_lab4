# Itmo-csa-lab4

- **Шукаев Олег Евгеньевич P3210**
- Вариант: `lisp | acc | neum | hw | tick | binary | trap | port | pstr | alg1 | superscalar`
  - `lisp`: Синтаксис языка Lisp. S-exp:
    1. Поддержка рекурсивных функций.
    2. Любое выражение - expression.
  - `acc`: Система команд выстроена вокруг аккумулятора.
  - `neum`: Фон Неймановская архитектура.
  - `hw`: Hardwired control unit.
  - `tick`: Процессор моделируется с точностью до такта.
  - `binary`: Бинарное представление машинного кода.
  - `trap`: Ввод-вывод осуществляется через систему прерываний.
  - `port`: Port-mapped.
  - `pstr`: Length-prefixed Pascal-строки.
  - `alg1`: Euler problem 4 (палиндромы-произведения трёхзначных чисел).
  - `superscalar`: Суперскалярная организация работы процессора (Parallel Flush).

---

## Язык программирования Lisp

Синтаксис основан на S-выражениях. Каждая конструкция записывается в виде списка в круглых скобках. Транслятор осуществляет построение AST для глубокого семантического анализа.

### Формальная грамматика
```ebnf
<program> ::= <expression_list>

<expression_list> ::= <expression> | <expression> <expression_list>

<expression> ::= <number>
               | <string>
               | <identifier>
               | "(" <special_form> ")"
               | "(" <function_call> ")"

<special_form> ::= <var_declaration>
                 | <set_assignment>
                 | <if_expression>
                 | <defun_declaration>
                 | <print_op>
                 | <io_op>
                 | <ptr_op>
                 | <binop_expression>

<var_declaration> ::= "defvar" <identifier> <expression>

<set_assignment> ::= "setq" <identifier> <expression>

<if_expression> ::= "if" <expression> <expression> <expression> 
                  | "if" <expression> <expression>

<defun_declaration> ::= "defun" <identifier> "(" <parameter_list> ")" <expression_list>

<function_call> ::= "funcall" <identifier> <argument_list>

<print_op> ::= "print" <expression> 
             | "print_str" <expression> 
             | "print_char" <expression>

<io_op> ::= "in" <number>

<ptr_op> ::= "read_ptr" <expression> 
           | "write_ptr" <expression> <expression>

<binop_expression> ::= <operator> <expression> <expression> <optional_expr_list>

<optional_expr_list> ::= "" | <expression> <optional_expr_list>

<operator> ::= "+" | "-" | "*" | "/" | "mod" | "=" | "!=" | "<" | ">"

<parameter_list> ::= "" | <identifier> <parameter_list>

<argument_list> ::= "" | <expression> <argument_list>

<identifier> ::= <letter> | <letter> <identifier_tail>

<identifier_tail> ::= <letter> | <digit> | "_" | <identifier_tail>

<string> ::= "\"" <string_content> "\""

<string_content> ::= "" | <character> <string_content>

<character> ::= <letter> | <digit> | " " | "," | "!" | "?" | "\n"

<letter> ::= "a" | "b" | ... | "z" | "A" | "B" | ... | "Z"

<digit> ::= "0" | "1" | ... | "9"

<number> ::= <digit> | <digit> <number>
```

### Семантика
- **Statement = Expression:** Любая языковая конструкция, включая `if` и `setq`, вычисляется и оставляет результат в аккумуляторе. Это позволяет использовать их вложенно (например, `(print (if p 1 2))`).
- **Переменное число аргументов:** Бинарные операторы поддерживают левую свертку: `(+ 1 2 3)` аппаратно разворачивается в `(+ (+ 1 2) 3)` на этапе построения AST.
- **Типизация:** Динамическая / бестиповая. Все данные обрабатываются как 32-битные знаковые машинные слова.
- **Строки (`pstr`):** Реализованы как *Pascal Strings* (длина + символы). Выделяются статически в памяти данных.
- **Рекурсия и контекст:** Язык поддерживает рекурсивные вызовы. Локальный контекст математических выражений и параметров функций безопасно сохраняется в аппаратный стек (`PUSH`/`POP`), что исключает состояние гонки.
- **Tail Call Optimization (TCO):** Для предотвращения переполнения стека реализована оптимизация хвостовой рекурсии. Если рекурсивный вызов является строго последней операцией, транслятор разворачивает его в безусловный переход `JMP`.
- **Прерывания:** Обработчик прерываний задается блоком `(defirq ...)`. При отсутствии явного обработчика компилятор генерирует безопасную заглушку `IRET`.

---

## Организация памяти

Модель: **Архитектура фон Неймана**.
Тип памяти: Однопортовая. Размер: `16384` машинных слов.

```text
        Main Memory (16384 x 32 bit)
+-----------------------------------+
| 0x0000 : JMP 3                    | <-- Обход вектора прерывания
| 0x0001 : JMP isr                  | <-- Вектор прерывания (IRQ Vector)
| 0x0002 : NOP                      |
| 0x0003 : _start: instruction_1    | <-- .text (Скомпилированные инструкции)
|   ...                             |
| 0x0400 : variable_1 / string_len  | <-- .data (Переменные, темпы AST, строки)
|   ...                             |
| 0x3FFF : stack_bottom             | <-- Стек (растет вверх к 0x0400)
+-----------------------------------+
```

---

## Система команд (ISA)

Архитектура: **Аккумуляторная (1-адресная)**.
Машинный код (`binary`): Инструкции имеют фиксированный размер **32 бита (4 байта)**:
* `Opcode`: 8 бит (операция).
* `Operand`: 24 бита (знаковое целое число в формате Little-Endian).


| Мнемоника | Опкод | Такты (F+E) | Описание |
|-----------|-------|-------|----------|
| `NOP`     | 0     | 2     | Пустая операция |
| `LD`      | 1     | 2     | `ACC ← M[arg]` |
| `LDI`     | 2     | 2     | `ACC ← arg` |
| `ST`      | 3     | 2*    | `M[arg] ← ACC` |
| `ADD`     | 4     | 2     | `ACC ← ACC + M[arg]` |
| `SUB`     | 5     | 2     | `ACC ← ACC - M[arg]` |
| `MOD`     | 6     | 2     | `ACC ← ACC % M[arg]` |
| `CMP`     | 7     | 2     | Установить флаги `Z` и `N` (`ACC - M[arg]`) |
| `JMP`     | 8     | 2     | Безусловный переход `IP ← arg` |
| `JZ/JNZ`  | 9/10  | 2     | Условные переходы по флагу Z |
| `IN`      | 11    | 2     | Чтение байта из FIFO очереди порта в `ACC` |
| `OUT`     | 12    | 2     | `OUT[port] ← ACC` |
| `PUSH`    | 13    | 2     | `M[SP] ← ACC; SP ← SP - 1` |
| `POP`     | 14    | 2     | `SP ← SP + 1; ACC ← M[SP]` |
| `CALL`    | 15    | 2     | `M[SP] ← IP; SP ← SP - 1; IP ← arg` |
| `RET`     | 16    | 2     | `SP ← SP + 1; IP ← M[SP]` |
| `IRET`    | 17    | 4     | Восстановление контекста из стека, включение `IE` |
| `HLT`     | 18    | 2     | Остановка симулятора |
| `LD_PTR`  | 19    | 3     | `ACC ← M[M[arg]]` |
| `ST_PTR`  | 20    | 3*    | `M[M[arg]] ← ACC` |
| `JLT/JGT` | 21/22 | 2     | Условные переходы по флагам Z и N |
| `MUL`     | 23    | 2     | `ACC ← ACC * M[arg]` |
| `DIV`     | 24    | 2     | `ACC ← ACC / M[arg]` |

*\* Операции `ST/ST_PTR` являются **отложенными (Deferred Store)**. Они аппаратно защелкиваются в теневой регистр, а физическая запись в память перекрывается с фазой `FETCH` следующей инструкции (Parallel Flush).*

---

## Транслятор

```bash
python translator.py <source.lisp> <output.bin> [debug.txt]
```
Работает в два прохода, обеспечивая изоляцию парсинга и кодогенерации:
1. **Front-end:** Лексический анализ и построение AST. Раннее выявление `SyntaxError`.
2. **Back-end:** Обход дерева в глубину. Включает предварительную регистрацию функций, оптимизацию TCO и назначение уникальных временных переменных.
Результат — бинарный файл формата `<i` и дизассемблерный дамп `debug.txt`.

---

## Модель процессора

```bash
python machine.py <binary.bin> <schedule.json>
```

### DataPath
![DataPath](img/dp_scheme_draft.png) 

Тракт данных реализует аккумуляторную архитектуру.
Связь флагов `Z` и `N` напрямую с мультиплексором данных (`MUX MEM IN`) обеспечивает возможность аппаратного сохранения регистра флагов в стек при прерываниях, минуя АЛУ.

**Управляющие сигналы:**
* `acc_latch`, `ip_latch`, `sp_latch`, `ir_latch` — защёлкивание соответствующих регистров.
* `sh_acc_latch`, `sh_addr_latch` — защёлкивание данных в теневой регистр.
* `mem_we` (Write Enable) — произвести физическую запись в ОЗУ.

**Управляющие сигналы (Селекторы / MUX Selectors):**
* `sel_addr` — выбор источника адреса для памяти: `IP` (Fetch), `SP` (Стек), `IR` (Прямая адресация), `SH_ADDR` (Parallel Flush).
* `sel_din` — выбор источника записи в память: `ACC`, `SH_ACC`, `IP` (для CALL) или `Flags (Z, N)` (для TRAP).

---

### Control Unit
![Control Unit](img/cu_scheme_draft.png)

Тип: **Hardwired FSM**. 
Отсутствует память микрокоманд и счетчик микрокоманд.

Устройство управления базируется на регистре состояния (FSM State Register), который хранит текущую фазу (например: `FETCH`, `EXECUTE`, аппаратные задержки или 4 такта прерывания `TRAP_1`–`TRAP_4`). Комбинационная матрица принимает на вход текущее состояние автомата и декодированный Опкод из `IR`, генерируя управляющие сигналы для тракта данных. 

#### Механизм Суперскаляра (Hazard Unit & Deferred Store)
В аккумуляторной архитектуре классический суперскаляр невозможен из-за зависимости по данным. Использован паттерн теневого регистра:
1. При команде `ST x` процессор **откладывает** запись. Адрес и данные аппаратно защёлкиваются в `SH_ACC` и `SH_ADDR`. Взводится триггер Hazard-блока. Память освобождается на 1 такт раньше.
2. Если следующая инструкция на фазе `EXECUTE` требует чтения (например, `LD` или `ADD`), Hazard-блок генерирует **Parallel Flush**. В этот же такт физически сбрасывается теневой регистр в память, а АЛУ получает новый операнд.
3. При структурном конфликте (две записи подряд или ветвление) автомат переходит во временное состояние `FLUSH_STALL` (заморозка конвейера на 1 такт) для принудительного сброса тени в память.

#### Ввод-вывод и Прерывания (Trap Controller)
* Внешнее устройство выставляет аппаратную линию `IRQ Line`.
* При `IRQ=True` и триггере `IE=True` (Interrupt Enable), на следующей фазе `FETCH` автомат перехватывает управление:
  1. За 4 физических такта автомат проходит состояния `TRAP_1` -> `TRAP_4`, сохраняя весь контекст в стек: `IP`, `ACC`, `Флаги (Z, N)`.
  2. Аппаратно сбрасывает флаг `IE` и форсирует `IP = 1` (Вектор прерывания).
* В журнале такты прерывания помечаются маркером `[ISR]`. Инструкция `IRET` за 4 такта восстанавливает контекст, прозрачно возвращая процессор в прерванный цикл.

---

## Тестирование

Тестирование осуществляется с помощью `pytest` и плагина `pytest-golden`.
Запуск: `pytest -v` (или `pytest --update-goldens`).

### Список тестов:
1. `hello` — Вывод Pascal-строки из памяти.
2. `cat` — Посимвольное эхо через асинхронные прерывания `[ISR]`.
3. `hello_user_name` — Интерактивный диалог через `Trap`. Демонстрирует защиту контекста прерыванием во время работы основного цикла.
4. `double_precision` — Эмуляция 64-битной арифметики (ручной перенос разряда / Carry) на 32-битной архитектуре.
5. `alg1` — Задача Эйлера № 4. Поиск самого большого палиндрома, образованного произведением двух трёхзначных чисел.
6. `expressions` — Синтетический тест вложенности "Statement as Expression".
7. `sort` — Пузырьковая сортировка массива через косвенную адресацию (указатели `LD_PTR` / `ST_PTR`).

### Пример работы

```text
  --- Simulation Trace ---
  Tick    2 | IP 0000 | JMP    3 | ACC=0
  Tick    4 | IP 0003 | LDI    0 | ACC=0
  Tick    6 | IP 0004 | ST     1024 | Deferred Store
  Tick    8 | IP 0005 | LDI    5000 | ACC=5000 | [Parallel Flush]
  Tick   10 | IP 0006 | ST     1025 | Deferred Store
  Tick   13 | IP 0007 | CALL   66 | ACC=5000
  Tick   15 | IP 0066 | IN     1 | ACC=0
  Tick   17 | IP 0067 | ST     1024 | Deferred Store
  Tick   19 | IP 0068 | LD     1024 | ACC=0 | [Parallel Flush]
  Tick   21 | IP 0069 | PUSH   0 | ACC=0
  Tick   23 | IP 0070 | LDI    0 | ACC=0
  Tick   25 | IP 0071 | ST     1038 | Deferred Store
  Tick   27 | IP 0072 | POP    0 | ACC=0 | [Parallel Flush]
  Tick   29 | IP 0073 | CMP    1038 | ACC=0
  Tick   31 | IP 0074 | JZ     77 | ACC=0
  Tick   33 | IP 0077 | LDI    1 | ACC=1
  Tick   35 | IP 0078 | CMP    1039 | ACC=1
  Tick   37 | IP 0079 | JZ     82 | ACC=1
  Tick   39 | IP 0080 | JMP    66 | ACC=1
  Tick   41 | IP 0066 | IN     1 | ACC=0
  Tick   43 | IP 0067 | ST     1024 | Deferred Store
  Tick   45 | IP 0068 | LD     1024 | ACC=0 | [Parallel Flush]
  Tick   47 | IP 0069 | PUSH   0 | ACC=0
  Tick   49 | IP 0070 | LDI    0 | ACC=0
  Tick   51 | IP 0071 | ST     1038 | Deferred Store
  Tick   53 | IP 0072 | POP    0 | ACC=0 | [Parallel Flush]
  Tick   55 | IP 0073 | CMP    1038 | ACC=0
  Tick   57 | IP 0074 | JZ     77 | ACC=0
  Tick   59 | IP 0077 | LDI    1 | ACC=1
  Tick   61 | IP 0078 | CMP    1039 | ACC=1
  Tick   63 | IP 0079 | JZ     82 | ACC=1
  Tick   65 | IP 0080 | JMP    66 | ACC=1
  Tick   67 | IP 0066 | IN     1 | ACC=0
  Tick   69 | IP 0067 | ST     1024 | Deferred Store
  Tick   71 | IP 0068 | LD     1024 | ACC=0 | [Parallel Flush]
  Tick   73 | IP 0069 | PUSH   0 | ACC=0
  Tick   75 | IP 0070 | LDI    0 | ACC=0
  Tick   77 | IP 0071 | ST     1038 | Deferred Store
  Tick   79 | IP 0072 | POP    0 | ACC=0 | [Parallel Flush]
  Tick   81 | IP 0073 | CMP    1038 | ACC=0
  Tick   83 | IP 0074 | JZ     77 | ACC=0
  Tick   85 | IP 0077 | LDI    1 | ACC=1
  Tick   87 | IP 0078 | CMP    1039 | ACC=1
  Tick   89 | IP 0079 | JZ 
  ... [TRUNCATED LOG] ...
  ed Store
  Tick 4532 | IP 0413 | POP    0 | ACC=4 | [Parallel Flush]
  Tick 4534 | IP 0414 | ADD    1091 | ACC=5
  Tick 4536 | IP 0415 | ST     1092 | Deferred Store
  Tick 4538 | IP 0416 | LD     1030 | ACC=5 | [Parallel Flush]
  Tick 4540 | IP 0417 | ST     1093 | Deferred Store
  Tick 4542 | IP 0418 | LD     1092 | ACC=5 | [Parallel Flush]
  Tick 4544 | IP 0419 | ST     1029 | Deferred Store
  Tick 4546 | IP 0420 | LD     1093 | ACC=5 | [Parallel Flush]
  Tick 4548 | IP 0421 | ST     1030 | Deferred Store
  Tick 4551 | IP 0422 | JMP    374 | ACC=5
  Tick 4553 | IP 0374 | LD     1029 | ACC=5
  Tick 4555 | IP 0375 | PUSH   0 | ACC=5
  Tick 4557 | IP 0376 | LD     1030 | ACC=5
  Tick 4559 | IP 0377 | ST     1087 | Deferred Store
  Tick 4561 | IP 0378 | POP    0 | ACC=5 | [Parallel Flush]
  Tick 4563 | IP 0379 | CMP    1087 | ACC=5
  Tick 4565 | IP 0380 | JLT    383 | ACC=5
  Tick 4567 | IP 0381 | LDI    0 | ACC=0
  Tick 4569 | IP 0382 | JMP    384 | ACC=0
  Tick 4571 | IP 0384 | CMP    1039 | ACC=0
  Tick 4573 | IP 0385 | JZ     396 | ACC=0
  Tick 4575 | IP 0396 | LDI    0 | ACC=0
  Tick 4577 | IP 0397 | LD     1029 | ACC=5
  Tick 4579 | IP 0398 | PUSH   0 | ACC=5
  Tick 4581 | IP 0399 | LD     1030 | ACC=5
  Tick 4583 | IP 0400 | ST     1090 | Deferred Store
  Tick 4585 | IP 0401 | POP    0 | ACC=5 | [Parallel Flush]
  Tick 4587 | IP 0402 | CMP    1090 | ACC=5
  Tick 4589 | IP 0403 | JLT    406 | ACC=5
  Tick 4591 | IP 0404 | LDI    0 | ACC=0
  Tick 4593 | IP 0405 | JMP    407 | ACC=0
  Tick 4595 | IP 0407 | CMP    1039 | ACC=0
  Tick 4597 | IP 0408 | JZ     424 | ACC=0
  Tick 4599 | IP 0424 | LDI    0 | ACC=0
  Tick 4601 | IP 0425 | RET    0 | ACC=0
  Tick 4603 | IP 0058 | ST     1037 | Deferred Store
  Tick 4605 | IP 0059 | POP    0 | ACC=0 | [Parallel Flush]
  Tick 4607 | IP 0060 | ST     1030 | Deferred Store
  Tick 4609 | IP 0061 | POP    0 | ACC=0 | [Parallel Flush]
  Tick 4611 | IP 0062 | ST     1029 | Deferred Store
  Tick 4613 | IP 0063 | LD     1037 | ACC=0 | [Parallel Flush]
  Tick 4615 | IP 0064 | HLT    0 | ACC=0
  --- Output ---
  ABCDE
```

**CI Pipeline:** Настроен GitHub Actions. Выполняются: `ruff format`, `ruff check`, статический анализатор `mypy` и прогон Golden-тестов `pytest`. Отключение линтеров не используется.