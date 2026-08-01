# PJSK 工资计算器

一个无数据库、无 Google Sheets 的 Streamlit 工资结算工具。保留原有的横向 Excel 排班方式，上传排班表后自动识别所有人员、岗位和工时，设置工价即可导出结算结果。

## 使用流程

1. 在 Excel、WPS 或 LibreOffice 中照常完成横向排班，并保存为 `.xlsx` 或 `.xlsm`。
2. 上传排班表；表内出现的所有人员会自动进入结算，无需再填写人员名单。
3. 按“班组 + 岗位”修改白班价和夜班价，并按需调整白班、夜班开始时间。
4. 检查工资汇总与明细，下载完整 Excel 或工资汇总 CSV。

上传的数据和工价只存在于当前 Streamlit 会话中。应用不使用数据库、不访问 Google Sheets，也不会持久化保存工资数据。

## 排班表格式

- 每个日期区块左上角是日期，右侧连续单元格是岗位名称。
- 日期下一行开始是时间段，例如 `15:00-16:00`、`0:00-0:30` 或 `23:30-0:30`。
- 人名填写在时间段和岗位的交叉单元格中；一个非空单元格就是一条排班记录。
- 日期区块可以左右并排或上下排列，首日和末日可以不是完整 24 小时。
- 每个工作表视为一个班组；不同工作表可以使用不同岗位。
- 支持 30 分钟等非整点时段。时间段跨越白班/夜班边界时，会拆分工时后分别计价。

导出的 Excel 包含：工资汇总、工资明细、工价设置和解析信息。

## 本地运行

要求 Python 3.10 或更高版本。

```bash
python -m pip install -r requirements.txt
python -m streamlit run salary_gui.py
```

## 免费部署到 Streamlit Community Cloud

1. 将项目推送到 GitHub 仓库。
2. 登录 [Streamlit Community Cloud](https://share.streamlit.io/) 并创建应用。
3. 选择仓库和分支，将入口文件设为 `salary_gui.py`。
4. 点击部署。此项目不需要填写 Secrets，也不需要购买数据库或存储服务。

Community Cloud 休眠或重启不会影响使用，因为每次结算都从上传的排班表重新计算；结算后下载结果即可。

## 项目结构

```text
salary_gui.py              Streamlit 界面
pjsk_salary/parser.py      横向排班 Excel 解析
pjsk_salary/salary.py      白班/夜班工时与工资计算
pjsk_salary/exporter.py    Excel / CSV 导出
tests/                     自动化测试
```

## 测试

```bash
python -m unittest discover -v
```

## License

MIT
