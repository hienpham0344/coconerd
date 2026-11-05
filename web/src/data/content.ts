export const features = [
  { id: 'topics', category: 'Hội thoại', title: 'Mỗi ý tưởng, một chỗ riêng.', description: 'Nhận diện những tin nhắn cùng chủ đề, kể cả khi nhiều câu chuyện đang diễn ra trong một kênh.', detail: 'Ngữ cảnh và các lượt trả lời giúp những ý tưởng tìm về đúng cuộc trò chuyện.', icon: 'messages', example: 'new-website' },
  { id: 'context', category: 'Hội thoại', title: 'Giữ mạch, giữ ngữ cảnh.', description: 'Tiếp nối chủ đề đang có khi cuộc trò chuyện quay lại, thay vì bắt đầu một nhánh mới từ đầu.', detail: 'Một chủ đề có thể đang hoạt động, tạm nghỉ, được tiếp nối hoặc đã khép lại.', icon: 'sprout', example: 'a-little-garden' },
  { id: 'summary', category: 'Tóm tắt', title: 'Bắt kịp, trong vài dòng.', description: 'Một bản tóm tắt giúp bạn đọc nhanh những điều quan trọng sau khi rời bàn phím.', detail: 'Xem những ý chính, điều đã thống nhất và câu hỏi còn mở; đối chiếu với hội thoại khi cần.', icon: 'sparkles', example: 'new-website' },
  { id: 'threads', category: 'Hội thoại', title: 'Câu chuyện có nơi để ở lại.', description: 'Tổ chức trao đổi thành những nhánh trò chuyện để cộng đồng dễ theo dõi hơn.', detail: 'Tác vụ thread dành cho bot Discord giữ liên kết đến tin nhắn nguồn, thay vì di chuyển tin gốc.', icon: 'hash', example: 'weekend-project' },
  { id: 'channels', category: 'Kiểm soát', title: 'Lắng nghe đúng nơi.', description: 'Chỉ tiếp nhận tin từ server đã bật và những kênh được quản trị viên cho phép.', detail: 'Không gian riêng vẫn riêng. Quản trị viên có thể tạm dừng nhận tin theo server.', icon: 'shield', example: null },
  { id: 'retention', category: 'Kiểm soát', title: 'Giữ lại có chủ đích.', description: 'Thời gian lưu tin nhắn do quản trị viên lựa chọn, phù hợp với cách cộng đồng hoạt động.', detail: 'Dữ liệu hết hạn được dọn theo cấu hình lưu trữ. Bạn có thể tìm hiểu thêm ở trang riêng tư.', icon: 'leaf', example: null },
];

export const faqs = [
  { category: 'Bắt đầu', question: 'Coconerd làm gì cho server của mình?', answer: 'Coconerd giúp gom các tin nhắn liên quan thành chủ đề, giữ mạch hội thoại và tạo tóm tắt để mọi người dễ theo dõi. Bạn có thể thử một không gian minh họa ngay trên website.' },
  { category: 'Bắt đầu', question: 'Có cần tài khoản để dùng website không?', answer: 'Trang công khai và trải nghiệm mẫu không cần đăng nhập. Dashboard dữ liệu thật yêu cầu đăng nhập Discord; chỉ chủ server hoặc người có quyền Administrator được quản trị server của mình. Dữ liệu trong bản trải nghiệm là minh họa, không kết nối với tài khoản Discord của bạn.' },
  { category: 'Bắt đầu', question: 'Làm sao thêm Coconerd vào Discord?', answer: 'Nhấn Thêm vào Discord để kiểm tra lời mời chính thức. Hiện link mời chưa được công bố. Trong lúc chờ, bạn có thể xem cách hoạt động và thử các cuộc trò chuyện mẫu.' },
  { category: 'Hội thoại', question: 'Tin nhắn gốc có bị di chuyển hoặc xóa không?', answer: 'Luồng tổ chức hội thoại giữ tin nhắn gốc ở kênh ban đầu. Bot Discord có thể tạo thread và đăng bản sao có liên kết đến nguồn để mọi người tiếp tục theo dõi.' },
  { category: 'Hội thoại', question: 'Vì sao một tin nhắn chưa có chủ đề?', answer: 'Tin nhắn được tiếp nhận trước rồi mới được phân loại. Tin quá ngắn hoặc thiếu ngữ cảnh có thể cần chờ thêm hội thoại; không phải mọi tin đều được gán thành một chủ đề.' },
  { category: 'Hội thoại', question: 'Chuyện gì xảy ra khi một chủ đề được khép lại?', answer: 'Chủ đề đã khép lại không tiếp nhận tin mới. Các cuộc trò chuyện tiếp theo sẽ được xem xét theo ngữ cảnh của chúng. Bạn có thể thử khép lại chủ đề trong bản minh họa và đặt lại mẫu khi muốn.' },
  { category: 'Tóm tắt', question: 'Tóm tắt có thay thế việc đọc tin gốc không?', answer: 'Tóm tắt giúp bắt kịp nhanh những ý chính nhưng AI có thể bỏ sót hoặc hiểu chưa đúng. Với quyết định quan trọng, hãy đối chiếu với các tin nhắn gốc.' },
  { category: 'Riêng tư', question: 'Coconerd có đọc tất cả kênh không?', answer: 'Không. Luồng tiếp nhận chỉ chấp nhận tin từ server đã bật và những kênh được cho phép. Quản trị viên chịu trách nhiệm lựa chọn phạm vi này.' },
  { category: 'Riêng tư', question: 'Nội dung hội thoại có được xử lý bởi AI không?', answer: 'Có. Khi sử dụng model thật, nội dung và ngữ cảnh được chọn sẽ gửi đến dịch vụ AI đã cấu hình. Quản trị viên nên thông báo cho thành viên và không chọn các kênh có nội dung không phù hợp để xử lý theo cách này.' },
  { category: 'Riêng tư', question: 'Thao tác trong bản thử có ảnh hưởng Discord không?', answer: 'Không. Mọi server, tin nhắn và tóm tắt trong bản trải nghiệm đều là dữ liệu mẫu. Thay đổi chỉ được lưu trong trình duyệt; nút Đặt lại mẫu giúp bắt đầu lại.' },
];

export function matchesText(text: string, query: string) {
  const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLocaleLowerCase('vi');
  return normalize(text).includes(normalize(query.trim()));
}
