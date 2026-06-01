# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: [Trần Quang Huy]
- **Student ID**: [2A202601010]
- **Date**: 2026-06-01

---

## I. Technical Contribution (15 Points)

Tôi xây dựng **Agent v2 (Improved)** để xử lý lỗi parser được phát hiện ở Agent v1.

- **Modules Implemented**:
  - `src/agent/agent_v2.py`: thêm `ReActAgentV2`, kế thừa Agent v1 và bổ sung parser recovery.
  - `tests/test_agent_v2.py`: thêm provider giả lập và ba test tái hiện lỗi, kiểm tra recovery, kiểm tra luồng end-to-end.
  - `run_agent.py`: thêm `--agent-version {v1,v2}`, mặc định chạy v2.
  - `tests/evaluation/run_evaluation.py`: thêm target `agent_v2`; target `all` chạy baseline, v1 và v2.

- **Code Highlights**:

```python
parsed_action = super()._parse_action(content)
if parsed_action is not None:
    return parsed_action

args = self._recover_dict(args_text)
if args is None:
    return None

logger.log_event(
    "AGENT_V2_ACTION_REPAIRED",
    {
        "tool_name": tool_name,
        "original_args": args_text,
        "repaired_args": args,
    },
)
```

- **Documentation**: Agent v2 vẫn giữ vòng lặp `Thought -> Action -> Observation -> Final Answer` của v1. Điểm khác biệt là khi parser JSON chuẩn thất bại, v2 thử phục hồi Python-style dictionary bằng `ast.literal_eval`, kiểm tra kết quả phải là `dict` có thể JSON serialize, ghi telemetry, rồi mới cho phép thực thi tool. `ast.literal_eval` chỉ đọc literal an toàn; agent không dùng `eval`.

---

## II. Debugging Case Study (10 Points)

### Problem Description

Agent v1 yêu cầu action arguments là JSON chuẩn:

```text
Action: search_courses({"topic": "Python", "level": "beginner"})
```

Tuy nhiên, LLM có thể trả dictionary theo cú pháp Python với dấu nháy đơn:

```text
Action: search_courses({'topic': 'Python', 'level': 'beginner'})
```

Tool name và arguments đều đúng về ý nghĩa, nhưng `json.loads()` của v1 từ chối cú pháp này. Khi demo với `max_steps=1`, Agent v1 không gọi được tool và kết thúc bằng thông báo vượt quá số bước.

### Log Source

Nguồn log: `logs/2026-06-01.log`, trace tạo lúc `2026-06-01T10:18:51` UTC bằng scripted provider để tái hiện lỗi ổn định.

```text
AGENT_LLM_OUTPUT: Action: search_courses({'topic': 'Python', 'level': 'beginner'})
AGENT_PARSE_ERROR: {"error": "NO_ACTION_PARSED"}
AGENT_MAX_STEPS_EXCEEDED: {"max_steps": 1}
```

Sau khi chạy Agent v2 với cùng action:

```text
AGENT_V2_ACTION_REPAIRED:
  original_args = {'topic': 'Python', 'level': 'beginner'}
  repaired_args = {"topic": "Python", "level": "beginner"}
TOOL_CALL: search_courses({"topic": "Python", "level": "beginner"})
TOOL_RESULT: PY101 - Python Beginner
AGENT_FINAL_ANSWER: PY101 - Python Beginner is available.
```

### Diagnosis

Nguyên nhân không nằm ở tool `search_courses`: tool hoạt động đúng khi nhận dictionary. Lỗi nằm ở ranh giới giữa output tự do của LLM và JSON parser nghiêm ngặt của Agent v1. Prompt đã yêu cầu JSON, nhưng prompt alone không bảo đảm model luôn tuân thủ format.

Telemetry giúp phân biệt rõ:

- Có `AGENT_LLM_OUTPUT`, nên provider đã trả kết quả.
- Có `AGENT_PARSE_ERROR`, nhưng không có `TOOL_CALL`, nên tool chưa từng được chạy.
- Có `AGENT_MAX_STEPS_EXCEEDED`, nên lỗi parser trực tiếp làm agent thất bại.

### Solution

Agent v2 áp dụng hai lớp phòng vệ:

1. Prompt bổ sung yêu cầu dùng raw JSON object với dấu nháy kép.
2. Parser recovery chỉ chạy sau khi parser v1 thất bại. Nó trích xuất object cân bằng ngoặc, dùng `ast.literal_eval`, xác nhận kiểu `dict`, kiểm tra JSON serialization và ghi event `AGENT_V2_ACTION_REPAIRED`.

Test xác minh:

```text
pytest -q tests/test_agent_v2.py tests/test_educourse_tools.py
12 passed
```

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

1. **Reasoning**: `Thought` giúp agent chia yêu cầu thành bước có thể kiểm tra: tìm khóa học, kiểm tra chỗ trống, xác thực coupon và tính học phí. Chatbot thường trả lời trôi chảy nhưng không có bằng chứng rằng dữ liệu khóa học là thật.

2. **Reliability**: Agent có thể kém chatbot ở câu hỏi đơn giản vì cần nhiều vòng gọi LLM hơn, tốn latency và token hơn. Agent cũng có thêm failure mode ở parser: tool đúng nhưng output `Action` sai format vẫn làm luồng dừng. Vì vậy Agent v2 cần guardrail ở lớp parser, không chỉ prompt engineering.

3. **Observation**: Observation biến suy luận tiếp theo thành phản ứng dựa trên dữ liệu. Ví dụ, `slots_left = 0` buộc agent không được giới thiệu lớp là còn chỗ; coupon invalid buộc agent không áp dụng giảm giá. Trong trace v2, observation từ `search_courses` cung cấp `PY101`, để model tạo câu trả lời cuối có căn cứ.

---

## IV. Future Improvements (5 Points)

- **Scalability**: Chuyển catalog dictionary sang database, cache truy vấn phổ biến và dùng async tool execution cho các tool độc lập.
- **Safety**: Thêm JSON Schema cho từng tool, allowlist tool name, giới hạn độ dài arguments và supervisor cho các action có tác động ghi dữ liệu.
- **Performance**: Theo dõi token, latency và số vòng theo từng version; đặt retry budget riêng cho parser recovery để tránh tăng chi phí không kiểm soát.
- **Reliability**: Ưu tiên native structured tool calling của provider khi có thể; giữ parser recovery làm fallback. Bổ sung phát hiện action lặp lại và semantic evaluator cho câu trả lời tương đương về ý nghĩa.

---

## Reproduction Notes

Chạy Agent v2:

```bash
python run_agent.py --agent-version v2 --provider openai
```

So sánh evaluation:

```bash
python -m tests.evaluation.run_evaluation --target all --provider openai
```

Trong môi trường hiện tại, focused tests chạy thành công. Full `pytest -q` chưa collect được vì máy thiếu dependency tùy chọn `llama_cpp`; `run_agent.py --help` chưa chạy được vì thiếu package `openai`.
