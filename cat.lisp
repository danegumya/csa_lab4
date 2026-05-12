(defvar done 0)

; Обработчик прерывания (Trap)
(defirq
    (setq char (in 1))
    (if (= char 0)
        (setq done 1)
        (setq __t (print char))
    )
)

; Основной цикл ожидания
(loop (= done 0)
    (setq dummy 0) ; NOP-эквивалент для траты тактов
)