# Kế hoạch triển khai Lab #3 cho Orchestrator

## Trạng thái thực thi

Đã hoàn tất các giai đoạn triển khai, QA và bàn giao trong plan này.

- Hoàn thiện tool registry, `ChatbotBaseline`, ReAct loop offline, safeguards và CLI demo.
- Bổ sung `autograder/test_agent_robustness.py`; không sửa autograder gốc hoặc dữ liệu mẫu.
- Cập nhật README và student guide để lệnh chạy/test khớp với workspace hiện tại.
- Xác minh cuối: `python -m pytest autograder/test_agent.py autograder/test_agent_robustness.py -v` — 19 passed; 5 customer query chạy đúng tool, status và số vòng dự kiến.

## 1. Mục tiêu và phạm vi

Hoàn thiện ChatbotBaseline và ReActAgent theo `student_guide.md`, dùng dữ liệu JSON cục bộ, vượt qua autograder và xử lý các lỗi được nêu trong hướng dẫn.

Tài liệu này khởi đầu là kế hoạch; trạng thái và kết quả thực thi hiện được ghi ở phần trên.

Giả định triển khai: dùng bộ chọn hành động mô phỏng có quy tắc để lab chạy offline, không cần API key. Tách bộ chọn hành động khỏi vòng lặp để có thể thay bằng LLM sau này. Ghi rõ đây là mô phỏng ReAct, không tuyên bố đã tích hợp LLM thật.

## 2. Những điểm đã đối chiếu trong repository

- `starter-code/template.py`: baseline hiện trả chuỗi; ReActAgent còn TODO.
- `starter-code/tools.py`: hai tool và TOOL_MAP đã có; kiểm tra, chỉ sửa khi cần.
- `autograder/test_agent.py`: có **8 test**, không phải 5 như student guide mô tả.
- Autograder yêu cầu kết quả dạng dictionary, khác annotation `-> str` trong skeleton.
- Câu hỏi chuyến bay + thời tiết yêu cầu `iterations == 3` và 3 trace entries; câu hỏi đơn và FAQ yêu cầu `iterations == 1`.
- Lệnh test đúng từ workspace hiện tại: `python -m pytest autograder/test_agent.py -v`.
- `raw-data/customer_queries.json` có thêm ca không tìm thấy chuyến bay, cần kiểm tra ngoài autograder.
- Không có SDK LLM trong requirements hiện tại.

## 3. Hợp đồng chung do Orchestrator chốt trước

### Kết quả và trace

- Baseline trả `{"status": "success", "answer": "...", "tool_calls": []}`; không gọi tool, không bịa giá vé hoặc thời tiết.
- Agent trả `{"status": "completed" | "max_iterations_reached", "answer": "...", "iterations": N, "trace": [...]}`.
- Mỗi vòng có một trace entry gồm `iteration`, `thought`, `action`, `observation`; entry kết thúc có thể thêm `answer`. `thought` chỉ là mô tả ngắn mục đích bước, ví dụ “Tra cứu thời tiết điểm đến”.
- `action` là `{"name": "...", "args": {...}}` hoặc `null`; observation lưu kết quả thực tế hoặc lỗi có cấu trúc.
- Reset trace khi bắt đầu mỗi `run()`; kết quả cũ không bị thay đổi khi chạy truy vấn mới.
- Câu hỏi kết hợp: vòng 1 tra chuyến bay, vòng 2 tra thời tiết, vòng 3 tổng hợp.
- Câu hỏi đơn: tra tool và tạo câu trả lời trong cùng vòng 1. FAQ trả lời trong vòng 1, không gọi tool.
- Tối đa 5 vòng mặc định. Với câu kết hợp và giới hạn 2 vòng, chọn kết quả `max_iterations_reached` vì chưa có vòng tổng hợp.
- Lỗi lặp lại cùng một hành động 2 lần: dừng sớm, trả `completed` cùng câu trả lời giải thích không thể tra cứu; chi tiết lỗi nằm trong trace. `completed` biểu thị đã kết thúc xử lý, không khẳng định tra cứu thành công.

### Dữ liệu và hành vi

- Đọc kết quả từ tools, không hardcode chuyến bay hoặc nhiệt độ vào câu trả lời.
- Nhận diện điểm đi/đến và nhu cầu chuyến bay, thời tiết, FAQ; không chỉ khớp nguyên văn câu hỏi mẫu.
- Hỗ trợ ngân sách `2 triệu`, `1.5 triệu`, `1,5 triệu`, `500k`; chuẩn hóa mã sân bay.
- Giữ quy ước lọc `price <= max_price` đang có trong tool; ghi rõ cách hiểu “giá tối đa”.
- Thiếu tham số cần thiết: yêu cầu bổ sung trong câu trả lời, không tự đoán hành trình.
- Không có chuyến bay phù hợp: thông báo rõ, không coi danh sách rỗng là lỗi để retry.
- FAQ Vinpearl: trả lời thận trọng, yêu cầu kiểm tra điều kiện vé hoặc liên hệ nơi bán; không tự đặt chính sách đổi trả.

## 4. Phân công worker

Các vai trò dưới đây dành cho lúc Orchestrator thực thi kế hoạch. Chỉ cho worker chạy song song khi phạm vi file độc lập; mọi sửa đổi `template.py` do một worker phụ trách.

| Vai trò | Phạm vi sở hữu | Công việc | Đầu ra / điều kiện bàn giao |
|---|---|---|---|
| Orchestrator | Kế hoạch, tích hợp và kiểm tra cuối | Chốt hợp đồng; kiểm tra môi trường; phân công; giải quyết khác biệt với test | Hợp đồng thống nhất và lệnh kiểm tra chạy được |
| Worker A — Tools | `starter-code/tools.py` | Xác minh registry, dữ liệu, lọc tuyến/giá và mã thành phố; sửa tối thiểu nếu phát hiện lỗi | Hai tool tương thích chữ ký hiện tại; ghi lại kết quả kiểm tra |
| Worker B — Agent | `starter-code/template.py` | Baseline; phân tích truy vấn; chọn/parse Action; dispatch; ReAct loop; tổng hợp; trace và safeguards | Hoàn thành 4 milestones, tuân thủ hợp đồng và xử lý lỗi |
| Worker C — QA | File test bổ sung mới, ví dụ `autograder/test_agent_robustness.py` | Thiết kế kiểm thử độc lập theo hợp đồng; kiểm tra lỗi JSON, tool, reset trace và giới hạn vòng lặp | Test tập trung vào hành vi; báo cáo lỗi tái hiện được |

Worker C không sửa test gốc để làm code vượt qua autograder. Worker A/B không sửa file của nhau; báo thay đổi giao diện cho Orchestrator trước khi tích hợp.

## 5. Trình tự thực thi

### Giai đoạn 0 — Chuẩn bị (Orchestrator)

1. Kiểm tra Python và dependencies; tạo môi trường ảo nếu cần.
2. Chạy autograder hiện trạng để ghi nhận lỗi ban đầu.
3. Chốt schema và quy tắc iterations ở mục 3; giao worker phạm vi rõ ràng.

### Giai đoạn 1 — Làm việc song song

- Worker A kiểm chứng tool và dữ liệu.
- Worker B triển khai baseline, parser và vòng lặp theo chữ ký tool hiện có.
- Worker C chuẩn bị ca test dựa trên hợp đồng và dữ liệu; chưa phụ thuộc chi tiết cài đặt nội bộ.

Các bước bắt buộc của Worker B:

1. Hoàn thiện baseline và sửa annotation kết quả.
2. Tách chọn hành động, parse/validate Action, thực thi tool và tổng hợp câu trả lời thành các phần rõ ràng.
3. Parse JSON bằng `json.loads()`; kiểm tra action là object, tên là chuỗi và args là object.
4. Chuẩn hóa tên bằng `.strip().lower()`; chỉ dispatch tên trong TOOL_MAP, không dùng `eval`.
5. Chuyển JSON sai thành observation `Invalid JSON format`; tool không tồn tại, tham số sai và exception thành lỗi có cấu trúc.
6. Đưa observation vào trạng thái vòng tiếp theo để bộ chọn hành động có thể sửa lỗi hoặc kết thúc.
7. Áp dụng giới hạn vòng và ngưỡng 2 lần lỗi bằng code; nếu có system prompt thì cũng ghi rõ quy tắc này.
8. Ghi trace cho mỗi vòng, gồm vòng lỗi và vòng kết thúc; tránh vượt giới hạn hoặc sai lệch một vòng.

### Giai đoạn 2 — Tích hợp và sửa lỗi (Orchestrator + worker phụ trách)

1. Nhận bàn giao Tools trước khi kết luận kiểm thử Agent.
2. Chạy 8 test gốc và các test bổ sung.
3. Gửi từng lỗi về đúng worker sở hữu file; tránh nhiều worker cùng sửa `template.py`.
4. Kiểm tra đủ 5 customer queries và chạy demo CLI.

### Giai đoạn 3 — Bàn giao (Orchestrator)

1. Cập nhật README với cách chạy, schema kết quả, cách đếm vòng và giới hạn của mô phỏng offline.
2. Sửa thông tin số test và đường dẫn lệnh test lỗi thời trong student guide nếu phạm vi triển khai bao gồm tài liệu.
3. Review diff, bảo đảm không thay dữ liệu mẫu hoặc nới assertion gốc để ép pass.
4. Báo cáo file đã sửa, kết quả test thực chạy và hạn chế còn lại.

## 6. Điểm cải tiến so với starter code

| Ưu tiên | Cải tiến | Giá trị / cách kiểm chứng |
|---|---|---|
| P0 — Cần cho demo | Thống nhất dictionary kết quả và cách đếm vòng | CLI hiển thị nhất quán; đáp ứng 8 test gốc |
| P0 — Cần cho demo | Parser nhận mã sân bay, nhiều cách viết ngân sách, nhu cầu đơn/kết hợp | Chạy được các câu hỏi mẫu và biến thể, không phụ thuộc nguyên văn |
| P0 — Cần cho demo | Câu trả lời lấy từ observation thật | Thể hiện rõ khác biệt baseline và agent; trace chỉ ra nguồn dữ liệu |
| P0 — Cần cho demo | Xử lý không có kết quả, lỗi tool và giới hạn vòng | Demo có thông báo kết thúc rõ ràng, không treo hoặc crash |
| P0 — Cần cho demo | CLI chọn kịch bản và in trace dễ đọc | Người trình diễn không phải sửa code giữa các tình huống |
| P1 — Sau khi demo chạy | Tách bộ chọn hành động qua một giao diện có thể thay thế | QA có thể cung cấp action giả lập để kiểm chứng lỗi JSON/tool; thuận tiện gắn LLM sau này |
| P1 — Sau khi demo chạy | Bổ sung kiểm thử reset trace, thiếu tham số, lỗi lặp lại | Bắt lỗi ngoài happy path mà autograder hiện chưa bao phủ |
| P1 — Sau khi demo chạy | Chuẩn hóa lỗi dữ liệu/tool và tài liệu kết quả | Phân biệt dữ liệu không tồn tại với truy vấn không có kết quả |
| P2 — Mở rộng tùy chọn | Tích hợp LLM thật hoặc giao diện web | Chỉ làm khi được yêu cầu thêm; cần ngân sách thời gian và phụ thuộc riêng |

P0 là phạm vi tối thiểu để trình diễn, không thay thế tiêu chí nghiệm thu đầy đủ. Giữ thay đổi nhỏ trong cấu trúc hiện có; chưa cần framework agent, database, web server hay SDK mới.

## 7. Chỉ dẫn xây dựng nhanh cho demo

### Lộ trình ưu tiên

Các mốc dưới đây là timebox tham khảo, không phải cam kết thời gian. Khi trễ mốc, giảm phần trình bày trước; giữ tính đúng của dữ liệu và safeguards.

1. **0–10 phút — Chốt đầu vào:** Orchestrator chuẩn bị môi trường, chạy test hiện trạng và giao hợp đồng mục 3. Worker A xác nhận tool; Worker C chuẩn bị checklist trong lúc Worker B bắt đầu code.
2. **10–35 phút — Luồng chính chạy được:** Worker B hoàn thiện baseline, parser tối thiểu và vòng lặp dùng TOOL_MAP. Ưu tiên câu hỏi kết hợp HAN → SGN, rồi mở sang câu đơn, FAQ và không có kết quả. Dùng JSON cục bộ, không chờ kết nối API.
3. **35–50 phút — Demo ổn định:** Hoàn thiện giới hạn vòng, xử lý lỗi và CLI. Worker C chạy 8 test gốc cùng 5 customer queries; Worker B sửa lỗi chặn demo.
4. **50–60 phút — Tổng duyệt:** Orchestrator chạy các kịch bản theo thứ tự bên dưới, kiểm tra terminal tiếng Việt và ghi lệnh vào README. Sau đó tiếp tục các kiểm tra P1 để nghiệm thu đầy đủ.

### Thiết lập và cách chạy

Ưu tiên Python đã cài sẵn; tạo `.venv` nếu workspace chưa có môi trường phù hợp. Không bắt buộc kích hoạt venv trên PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r starter-code/requirements.txt
.\.venv\Scripts\python.exe -m pytest autograder/test_agent.py -v
.\.venv\Scripts\python.exe -X utf8 starter-code/template.py
```

Worker B bổ sung CLI bằng `argparse` của thư viện chuẩn, giữ hành vi chạy mặc định hiện có:

- Không có tham số: chạy baseline và agent với câu hỏi kết hợp mẫu.
- `--query "..."`: chạy câu hỏi tùy chọn qua baseline và agent.
- `--max-iterations N`: điều chỉnh giới hạn để trình diễn safeguard.
- `--show-trace`: in từng bước với tên tool, args và observation; `thought` chỉ mô tả ngắn mục đích thao tác.

CLI cần hiển thị: câu hỏi, câu trả lời baseline, câu trả lời agent, status, số vòng và trace khi được chọn. Gắn nhãn “Dữ liệu mô phỏng cục bộ” để người xem hiểu vé/thời tiết không phải tra cứu thời gian thực.

Các lệnh dự kiến sau khi bổ sung CLI:

```powershell
.\.venv\Scripts\python.exe -X utf8 starter-code/template.py --show-trace
.\.venv\Scripts\python.exe -X utf8 starter-code/template.py --query "Có chuyến bay nào từ HAN đi DAD giá dưới 1.5 triệu không?" --show-trace
.\.venv\Scripts\python.exe -X utf8 starter-code/template.py --query "Tìm chuyến bay từ SGN đi HAN dưới 500k." --show-trace
.\.venv\Scripts\python.exe -X utf8 starter-code/template.py --max-iterations 2 --show-trace
```

### Kịch bản trình diễn 3–5 phút

| Thứ tự | Nội dung | Điểm cần chỉ ra |
|---|---|---|
| 1 | Baseline và agent nhận cùng câu hỏi HAN → SGN + thời tiết | Baseline không có dữ liệu tra cứu; agent dùng 2 tool và tổng hợp ở vòng 3 |
| 2 | Mở trace của câu hỏi kết hợp | Args đúng tuyến/ngân sách; observation có chuyến bay và gợi ý trang phục từ JSON |
| 3 | Chạy câu hỏi đơn HAN → DAD | Agent chỉ dùng tool cần thiết, hoàn thành trong 1 vòng |
| 4 | Chạy SGN → HAN dưới 500k | Không có kết quả được xử lý rõ ràng, không tạo vé giả |
| 5 | Chạy câu kết hợp với max_iterations=2 | Agent dừng có kiểm soát và trả status phù hợp |

**Cổng “đủ để demo”:** 8 test gốc pass; các kịch bản trên chạy được bằng lệnh copy/paste; trace có dữ liệu tool thật; không cần API key; không có exception chưa xử lý trong các ca trình diễn. Hoàn thành cổng này thì cố định luồng demo trước khi mở rộng P1/P2.

Nếu thiếu thời gian: giữ CLI văn bản và mô phỏng offline; hoãn màu sắc, UI web và LLM thật. Không hardcode đáp án để rút ngắn triển khai. Nếu có test còn fail, ghi rõ và tiếp tục sửa, không công bố demo đã đạt cổng.

## 8. Tiêu chí nghiệm thu đầy đủ

- [ ] Toàn bộ 8 test gốc pass.
- [ ] 5 customer queries chạy đúng loại tool và trả lời dựa trên dữ liệu.
- [ ] HAN → SGN, tối đa 2 triệu: tìm VN213 và VJ151; câu trả lời kết hợp có thời tiết/gợi ý trang phục SGN, 3 vòng và 3 trace entries.
- [ ] HAN → DAD, tối đa 1.5 triệu: có QH202, 1 vòng.
- [ ] Thời tiết DAD: có 28°C, 1 vòng.
- [ ] FAQ: không gọi tool, không bịa chính sách.
- [ ] SGN → HAN, tối đa 500k: thông báo không có kết quả phù hợp.
- [ ] Tên tool khác hoa/thường hoặc thừa khoảng trắng vẫn dispatch được.
- [ ] JSON sai, tool lạ, tham số sai và tool lỗi không làm chương trình crash.
- [ ] Lỗi lặp lại dừng sau 2 lần; số vòng không vượt max_iterations.
- [ ] Gọi lại cùng agent không mang trace hoặc dữ liệu truy vấn cũ sang truy vấn mới.
- [ ] Test xác minh đường đi của tool/observation, không chỉ đối chiếu chuỗi trả lời đã hardcode.

Lệnh nghiệm thu từ thư mục gốc:

```powershell
python -m pytest autograder/test_agent.py -v
python -m pytest autograder/test_agent_robustness.py -v
python starter-code/template.py
```

File test bổ sung sẽ được tạo trong giai đoạn triển khai; các lệnh trên là kế hoạch kiểm tra, chưa phải kết quả đã chạy.
