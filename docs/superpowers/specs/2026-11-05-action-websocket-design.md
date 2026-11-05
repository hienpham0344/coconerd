# Action WebSocket

Giảm thời gian gom tin vào Thread theo phương án push đã trao đổi. Giữ checkout hiện tại vì pipeline PostgreSQL/receipt đang có thay đổi chưa commit; không commit, migrate hoặc restart production.

PostgreSQL phát tín hiệu `coconerd_jobs` và `coconerd_actions` trong transaction tạo job/action; chỉ giao tín hiệu khi commit. Worker và mỗi API process dùng một kết nối LISTEN riêng trong pool, tự kết nối lại. Payload rỗng, không truyền nội dung chat hoặc credential.

Bot mở `/api/v1/actions/events` bằng header `X-API-Key`. WebSocket gửi `actions_available` khi kết nối và khi có action, cùng heartbeat mỗi 20 giây. Socket chỉ đánh thức vòng claim HTTP; lease, ACK, retry và receipt vẫn là nguồn quyết định. Khi mất socket hoặc notification, polling 2,5 giây của bot và 1 giây mặc định của worker vẫn hoạt động. Không ngủ giữa các action khi hàng đợi còn việc.

Không thêm dependency, Redis, response cache hoặc thay đổi model. Kiểm chứng auth WebSocket, tín hiệu sau commit/rollback, reconnect, cancellation/shutdown, polling fallback và xử lý backlog; test offline không gọi Discord/Meta/Railway thật.
