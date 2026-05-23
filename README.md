# PJSK 排班与工资计算系统

一个基于 Streamlit 的排班、工价配置和工资统计工具，支持：
- 按活动周期排班
- 多队伍切换
- 不同队伍使用不同工种
- 白班/夜班工价设置
- 工资汇总
- 导出 Excel / CSV
- 手动存档与读档

## 环境要求

- Python 3.10 及以上

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行方式

```bash
streamlit run salary_gui.py
```

如果你的环境里 `streamlit` 命令不可用，也可以用：

```bash
python -m streamlit run salary_gui.py
```

## 主要功能

- 自动获取简中服活动排期
- 按当前日期默认选中当前活动
- 支持多队伍独立排班
- 每个队伍独立设置工种和工价
- 支持工资统计与导出 Excel

## 存档说明

- 点击侧边栏按钮可手动保存和读取进度
- 导出的工资表支持 Excel 和 CSV 格式

## License

本项目使用 MIT License