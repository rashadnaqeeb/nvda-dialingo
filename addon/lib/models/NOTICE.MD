# License Notice

## File `lid.176.q1m.ftz`

fastText language identification, derived from `lid.176.bin` published by Facebook AI Research at
https://fasttext.cc/docs/en/language-identification.html, distributed under the
[Creative Commons Attribution-Share-Alike License 3.0](https://creativecommons.org/licenses/by-sa/3.0/).

The published compressed model, `lid.176.ftz` (916 KB), was pruned to 100,000 features and has no character
n-grams, so common short words ("no", "army", "Oui") are unknown to it. This file is the full model quantized
with fastText's own tool at a cutoff of 1,000,000 features, character n-grams kept:

    fasttext quantize -input none -output lid.176 -cutoff 1000000 -qnorm -dsub 2

E. Grave, P. Bojanowski, P. Gupta, A. Joulin, T. Mikolov, "Learning Word Vectors for 157 Languages", LREC 2018.
A. Joulin, E. Grave, P. Bojanowski, T. Mikolov, "Bag of Tricks for Efficient Text Classification", 2016.
