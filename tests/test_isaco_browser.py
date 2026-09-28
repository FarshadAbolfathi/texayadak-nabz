"""تست بخش‌های تست‌پذیر اتوماسیون مرورگر ایساکو (بدون اجرای مرورگر)."""

import json

from nabz.sources.isaco_browser import _js_click_excel, _js_fill_login


class TestLoginJs:
    def test_includes_all_fields_safely(self):
        js = _js_fill_login("4199037", "4073464450", "p@ss'\"x")
        assert "#Scus" in js
        assert "#UserName" in js
        assert "#Password" in js
        # مقادیر با JSON امن‌سازی شده‌اند (نه تزریق خام)
        assert json.dumps("p@ss'\"x") in js

    def test_dispatches_input_event_for_react(self):
        js = _js_fill_login("1", "2", "3")
        assert "dispatchEvent" in js
        assert "input" in js

    def test_clicks_submit(self):
        js = _js_fill_login("1", "2", "3")
        assert "btn.click()" in js


class TestExcelJs:
    def test_targets_excel_icon(self):
        js = _js_click_excel()
        assert "k-i-excel" in js

    def test_guards_disabled_button(self):
        js = _js_click_excel()
        assert "disabled" in js
        assert "btn-disabled" in js
