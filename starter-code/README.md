# Starter Code — Lab #3

Lab này so sánh một chatbot baseline với ReAct Agent. Agent chạy hoàn toàn offline: chọn hành động theo quy tắc, gọi tool từ dữ liệu JSON cục bộ, rồi ghi lại Thought–Action–Observation. Không cần API key hay kết nối Internet.

## Cấu trúc

- `template.py`: triển khai `ChatbotBaseline`, `ReActAgent` và CLI demo.
- `tools.py`: registry gồm `get_flight_info` và `get_weather_forecast`.
- `../raw-data/flight_data.json`: dữ liệu chuyến bay mô phỏng.
- `../raw-data/weather_data.json`: dữ liệu thời tiết và gợi ý trang phục mô phỏng.
- `../raw-data/customer_queries.json`: năm câu hỏi mẫu để kiểm tra/demo.

Tool đọc dữ liệu theo đường dẫn tương đối với workspace, nên luôn chạy cùng dữ liệu cục bộ. Giá vé tối đa được hiểu là `price <= max_price`.

## Chạy từ thư mục gốc của workspace

Các lệnh dưới đây giả định thư mục hiện tại là thư mục chứa `starter-code`, `autograder` và `raw-data`.

```powershell
python -m pip install -r starter-code/requirements.txt
python -m pytest autograder/test_agent.py -v
python -X utf8 starter-code/template.py --show-trace
```

Autograder gốc hiện có 8 test. Nếu có file kiểm tra mở rộng, có thể chạy thêm:

```powershell
python -m pytest autograder/test_agent_robustness.py -v
```

Nếu muốn dùng virtual environment trên PowerShell mà không cần kích hoạt nó:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r starter-code/requirements.txt
.\.venv\Scripts\python.exe -m pytest autograder/test_agent.py -v
```

## Demo CLI

```text
python -X utf8 starter-code/template.py [--query "..."] [--max-iterations N] [--show-trace]
```

- Không có cờ nào: chạy câu hỏi mẫu về HAN → SGN và thời tiết SGN.
- `--query`: thay câu hỏi mẫu; câu hỏi được chạy qua cả baseline và agent.
- `--max-iterations`: đặt số vòng ReAct tối đa, mặc định là `5`.
- `--show-trace`: in JSON trace theo từng vòng.

Các kịch bản demo nhanh:

```powershell
# Câu hỏi kết hợp: 2 lần gọi tool và 1 vòng tổng hợp
python -X utf8 starter-code/template.py --show-trace

# Câu hỏi một tool
python -X utf8 starter-code/template.py --query "Có chuyến bay nào từ HAN đi DAD giá dưới 1.5 triệu không?" --show-trace

# Không có chuyến bay phù hợp
python -X utf8 starter-code/template.py --query "Tìm cho tôi chuyến bay từ SGN đi HAN dưới 500k." --show-trace

# Minh họa safeguard khi chưa đủ vòng để tổng hợp
python -X utf8 starter-code/template.py --max-iterations 2 --show-trace
```

CLI luôn in nhãn “Dữ liệu mô phỏng cục bộ”, câu hỏi, câu trả lời baseline, câu trả lời agent, `status` và số vòng. Trace chỉ được in khi dùng `--show-trace`.

## Hợp đồng kết quả

`ChatbotBaseline().query(...)` trả về dictionary không gọi tool:

```python
{
    "status": "success",
    "answer": "...",
    "tool_calls": [],
}
```

`ReActAgent(...).run(...)` trả về:

```python
{
    "status": "completed" | "max_iterations_reached",
    "answer": "...",
    "iterations": 3,
    "trace": [...],
}
```

`iterations` luôn bằng số entry trong `trace`. Mỗi entry có `iteration`, `thought`, `action` và `observation`; entry kết thúc có thể có thêm `answer`. `action` là dictionary gồm `name` và `args`, hoặc `null` khi agent tổng hợp/kết thúc. Observation lưu kết quả tool thực tế hoặc lỗi có cấu trúc, vì vậy trace cho thấy câu trả lời được tạo từ dữ liệu nào.

Agent reset trace cho mỗi lần `run()`, giới hạn số vòng, chuẩn hóa tên tool và chuyển lỗi JSON/tool/tham số thành observation thay vì làm chương trình dừng. Đây là mô phỏng ReAct có tính quyết định; dữ liệu vé và thời tiết không phải thông tin thời gian thực.
