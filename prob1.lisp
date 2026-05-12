(defvar sum 0)
(defvar i 1)

(loop (!= i 1000)
    (if (= (mod i 3) 0)
        (setq sum (+ sum i))
        (if (= (mod i 5) 0)
            (setq sum (+ sum i))
            0
        )
    )
    (setq i (+ i 1))
)
(print sum)