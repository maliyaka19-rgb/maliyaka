"""
Calculator & Web Tools Tests (Turkish QA)
=========================================
Tests SafeCalculator (AST-based). SafeCalculator returns
{'success': True/False, 'result'/'error', 'expression'}.
"""
import sys
import os
import math
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_tools import SafeCalculator


@pytest.fixture
def calc():
    return SafeCalculator()


# ============================================================
# SAFE CALCULATOR — Arithmetic
# ============================================================

class TestCalculatorArithmetic:
    def test_addition(self, calc):
        assert calc.evaluate("2 + 3")["result"] == 5

    def test_subtraction(self, calc):
        assert calc.evaluate("10 - 4")["result"] == 6

    def test_multiplication(self, calc):
        assert calc.evaluate("6 * 7")["result"] == 42

    def test_division(self, calc):
        assert calc.evaluate("10 / 4")["result"] == 2.5

    def test_floor_division(self, calc):
        assert calc.evaluate("10 // 3")["result"] == 3

    def test_modulo(self, calc):
        assert calc.evaluate("10 % 3")["result"] == 1

    def test_power(self, calc):
        assert calc.evaluate("2 ** 10")["result"] == 1024

    def test_complex_expression(self, calc):
        # (191.5 + 7.5) * 2 = 398
        assert calc.evaluate("(191.5 + 7.5) * 2")["result"] == 398

    def test_operator_precedence(self, calc):
        # 2 + 3 * 4 = 14 (not 20)
        assert calc.evaluate("2 + 3 * 4")["result"] == 14

    def test_negative_numbers(self, calc):
        assert calc.evaluate("-5 + 3")["result"] == -2


# ============================================================
# SAFE CALCULATOR — Functions
# ============================================================

class TestCalculatorFunctions:
    def test_sqrt(self, calc):
        assert calc.evaluate("sqrt(144)")["result"] == 12.0

    def test_sin_zero(self, calc):
        assert calc.evaluate("sin(0)")["result"] == 0.0

    def test_cos_zero(self, calc):
        assert calc.evaluate("cos(0)")["result"] == 1.0

    def test_log_e(self, calc):
        assert abs(calc.evaluate("log(e)")["result"] - 1.0) < 1e-9

    def test_abs(self, calc):
        assert calc.evaluate("abs(-42)")["result"] == 42

    def test_round(self, calc):
        assert calc.evaluate("round(3.14159, 2)")["result"] == 3.14

    def test_min(self, calc):
        assert calc.evaluate("min(3, 1, 2)")["result"] == 1

    def test_max(self, calc):
        assert calc.evaluate("max(3, 1, 2)")["result"] == 3

    def test_nested_function(self, calc):
        # sqrt(16) + sqrt(9) = 4 + 3 = 7
        assert calc.evaluate("sqrt(16) + sqrt(9)")["result"] == 7


# ============================================================
# SAFE CALCULATOR — Constants
# ============================================================

class TestCalculatorConstants:
    def test_pi(self, calc):
        assert abs(calc.evaluate("pi")["result"] - math.pi) < 1e-9

    def test_e_constant(self, calc):
        assert abs(calc.evaluate("e")["result"] - math.e) < 1e-9

    def test_pi_in_expression(self, calc):
        assert abs(calc.evaluate("2 * pi")["result"] - 2 * math.pi) < 1e-9


# ============================================================
# SAFE CALCULATOR — Error Handling (Security)
# ============================================================

class TestCalculatorSecurity:
    def test_rejects_import(self, calc):
        r = calc.evaluate("__import__('os').system('ls')")
        assert r["success"] is False

    def test_rejects_attribute_access(self, calc):
        r = calc.evaluate("(1).__class__")
        assert r["success"] is False

    def test_rejects_unknown_function(self, calc):
        r = calc.evaluate("eval('1+1')")
        assert r["success"] is False

    def test_rejects_empty(self, calc):
        r = calc.evaluate("")
        assert r["success"] is False

    def test_rejects_syntax_error(self, calc):
        r = calc.evaluate("2 +* 3")
        assert r["success"] is False


# ============================================================
# TURKISH QA — Real-world math problems
# ============================================================

class TestTurkishMathQA:
    def test_question_1(self, calc):
        # "Bir kargo 3 kutudan oluşuyor. Her kutuda 24 ürün var. Toplam kaç ürün?"
        assert calc.evaluate("3 * 24")["result"] == 72

    def test_question_2(self, calc):
        # "500 TL'lik alışverişe %18 KDV eklenirse toplam ne olur?"
        assert calc.evaluate("500 * 1.18")["result"] == 590.0

    def test_question_3(self, calc):
        # "Bir dikdörtgenin alanı: 12m x 8m"
        assert calc.evaluate("12 * 8")["result"] == 96

    def test_question_4(self, calc):
        # "Bir sayının %25'i 50 ise sayı kaçtır?" => 50 / 0.25
        assert calc.evaluate("50 / 0.25")["result"] == 200

    def test_question_5(self, calc):
        # "ortalama: (85 + 90 + 78 + 92) / 4"
        assert calc.evaluate("(85 + 90 + 78 + 92) / 4")["result"] == 86.25
