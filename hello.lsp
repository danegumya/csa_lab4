(defun main ()
    (print "Euler 1 Problem")
    (setq sum 0)
    (setq i 0)

    (loop
        (if (= i 1000) (break))

        (setq is_match 0)

        ; Проверяем делимость на 3
        (if (= (% i 3) 0)
            (setq is_match 1)
            0) ; else заглушка

        ; Проверяем делимость на 5
        (if (= (% i 5) 0)
            (setq is_match 1)
            0)

        ; Если подошло
        (if (= is_match 1)
            (setq sum (+ sum i))
            0)

        (setq i (+ i 1))
    )

    (print "Answer:")
    (print sum)
)