# Changelog

All notable changes to this project will be documented in this file.

## [v1.4.1] - 2026-07-03
- 根據客戶反饋調整前台 UI：移除頂部通知標籤、顯著放大品牌圓形 Logo 尺寸以強化品牌感。

## [v1.4.0] - 2026-07-02
- 引入 Quill.js 富文本編輯器，支援通知欄與品牌簡介的自訂字型、色彩美編與外部格式貼上功能。
- 後台品牌簡介改為帶有工具列的富文本 WYSIWYG 編輯器，儲存時以 HTML 字串存入 Firestore。
- 前台品牌簡介使用 Jinja2 `| safe` 過濾器渲染，正確顯示富文本樣式。

## [v1.3.0] - 2026-07-02
- 新增管理員後台「客戶名單刪除」功能，可從 Firestore 永久移除客戶個資。
- 新增後端 /api/check-status 端點，前台頁面載入時驗證 localStorage 紀錄是否仍存在於 Firestore。
- 已被刪除的客戶下次進站時，系統將自動失效 localStorage 狀態並重新顯示全螢幕填單遮罩。

## [v1.2.1] - 2026-07-02
- 新增管理員後台動態修改前台品牌簡介/歡迎詞功能。

## [v1.2.0] - 2026-07-02
- 新增管理員後台動態修改前台 Logo 圖片網址與品牌名稱之功能。
