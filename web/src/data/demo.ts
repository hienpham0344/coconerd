import type { Guild, Message, ModelConfig, Summary, Topic } from '../types';

export const demoGuilds: Guild[] = [
  { guild_id: 'garden', name: 'Coconerd Garden', enabled: true, allowed_channel_ids: ['general', 'product', 'creative'], retention_days: 365 },
  { guild_id: 'studio', name: 'The Little Studio', enabled: true, allowed_channel_ids: ['ideas', 'design'], retention_days: 90 },
];
const now = Date.now();
const ago = (minutes: number) => new Date(now - minutes * 60_000).toISOString();
export const demoTopics: Topic[] = [
  { topic_id: 'a-little-garden', guild_id: 'garden', title: 'Một khu vườn nhỏ cho cộng đồng', description: 'Cùng tạo một không gian để những ý tưởng tự do lớn lên. Những bước đầu cho server và trải nghiệm thành viên mới.', status: 'ACTIVE', last_activity: ago(4), discord_thread_id: null, message_count: 8 },
  { topic_id: 'weekend-playlist', guild_id: 'garden', title: 'Playlist cho một cuối tuần chậm rãi', description: 'Những bản nhạc nhẹ để ngồi làm việc, đọc sách, hoặc đơn giản là không làm gì cả.', status: 'ACTIVE', last_activity: ago(18), discord_thread_id: null, message_count: 6 },
  { topic_id: 'new-website', guild_id: 'garden', title: 'Góc ý tưởng: website mới của chúng mình', description: 'Moodboard thiên nhiên, màu sắc và những chi tiết tương tác cho ngôi nhà mới của Coconerd.', status: 'RESUMED', last_activity: ago(42), discord_thread_id: null, message_count: 5 },
  { topic_id: 'weekend-project', guild_id: 'garden', title: 'Dự án cuối tuần — có ai muốn tham gia?', description: 'Một công cụ nhỏ, một nhóm bạn và hai ngày cuối tuần. Cùng thử xây điều gì đó hữu ích.', status: 'ACTIVE', last_activity: ago(120), discord_thread_id: null, message_count: 5 },
  { topic_id: 'book-corner', guild_id: 'garden', title: 'Cuốn sách bạn đang đọc', description: 'Chia sẻ những trang sách hay và những câu chuyện còn ở lại sau khi gấp sách.', status: 'DORMANT', last_activity: ago(1440), discord_thread_id: null, message_count: 4 },
  { topic_id: 'welcome', guild_id: 'garden', title: 'Lời chào từ những người bạn mới', description: 'Một vòng giới thiệu nho nhỏ để chúng mình biết nhau hơn.', status: 'CLOSED', last_activity: ago(2880), discord_thread_id: null, message_count: 4 },
  { topic_id: 'studio-design', guild_id: 'studio', title: 'Thiết kế một điều thật giản dị', description: 'Thử nghiệm bố cục, chất liệu và những khoảng trống có chủ đích.', status: 'ACTIVE', last_activity: ago(15), discord_thread_id: null, message_count: 4 },
];

const conversations: Record<string, [string, string][]> = {
  'a-little-garden': [['Linh', 'Mình muốn server là một góc nhỏ thật dễ chịu, nơi mọi người có thể chia sẻ ý tưởng mà không ngại 🌱'], ['Minh', 'Hay đó! Mình nghĩ nên có một kênh chung và một góc cho các dự án nhỏ.'], ['An', 'Tin nhắn trôi nhanh quá, có cách nào giữ lại những cuộc nói chuyện hay không nhỉ?'], ['Linh', 'Coconerd sẽ gom các tin cùng chủ đề lại, rồi có một bản tóm tắt để ai vào sau cũng theo kịp.'], ['Huy', 'Vậy nhóm mình không phải tạo thread bằng tay cho từng ý tưởng nữa.'], ['Minh', 'Bắt đầu với #general, #product và #creative nhé?'], ['An', 'Đồng ý. Cuối tuần mình sẽ soạn lời chào cho thành viên mới.'], ['Linh', 'Chốt vậy nha. Một khu vườn nhỏ, từ những cuộc trò chuyện lớn dần ✨']],
  'weekend-playlist': [['An', 'Có ai có playlist ambient nhẹ để làm việc không?'], ['Huy', 'Mình thường nghe tiếng mưa và một ít piano.'], ['Linh', 'Thêm vài bài acoustic nữa là vừa đẹp 🌙'], ['Minh', 'Mình góp một chút jazz chậm.'], ['An', 'Để mình gom thành playlist chung nhé.'], ['Huy', 'Đặt tên “Một cuối tuần chậm rãi” đi!']],
};
export function demoMessages(topic: Topic): Message[] {
  const entries = conversations[topic.topic_id] || [['Linh', topic.description], ['Minh', 'Mình thích ý tưởng này. Cùng ghi lại các bước tiếp theo nhé.'], ['An', 'Mình sẽ chuẩn bị một bản nháp để cả nhóm xem.'], ['Huy', 'Cuối tuần chúng mình cùng trao đổi thêm nha 🌿']];
  return entries.map(([author, content], index) => ({ message_id: `${topic.topic_id}-${index}`, channel_id: 'general', author_id: author, author_name: author, content, created_at: ago((entries.length - index) * 8) })).reverse();
}
export function demoSummary(topic: Topic): Summary {
  return { version: 2, source_message_ids: demoMessages(topic).map(m => m.message_id), summary: topic.description, key_points: topic.topic_id === 'a-little-garden' ? ['Tạo không gian chia sẻ ý tưởng gần gũi, dễ tham gia.', 'Bắt đầu với ba kênh: general, product và creative.', 'Dùng Coconerd để gom chủ đề và giúp thành viên mới theo kịp.'] : ['Nhóm đang cùng trao đổi và thu thập ý kiến.', 'Chuẩn bị bản nháp trước buổi thảo luận tiếp theo.'], open_questions: ['Những ý tưởng nào nên được ưu tiên trong tuần tới?'] };
}
export const defaultModel: ModelConfig = { provider: 'meta', model_id: 'muse-spark-1.3', temperature: 0, max_tokens: 2048 };
