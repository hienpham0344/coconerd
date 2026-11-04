import { useEffect, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronDown, Hash, Leaf, LockKeyhole, MessageCircle, RefreshCw, Search, ShieldCheck, Sparkles } from 'lucide-react';
import { Flower } from '../components/Brand';
import { PublicLayout, PageIntro } from '../components/PublicLayout';
import { errorMessage } from '../components/Feedback';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { request } from '../data/api';
import { faqs, matchesText } from '../data/content';
import type { PublicStatus, SiteConfig } from '../types';

function Features() {
  return <PublicLayout active="/features" title="Tính năng">
    <PageIntro eyebrow="NHỮNG ĐIỀU COCONERD CÓ THỂ GIÚP" title={<>Mỗi câu chuyện,<br /><em>một mạch riêng.</em></>}>Giữ những ý tưởng liên quan ở gần nhau, bắt kịp điều đã bỏ lỡ và để cộng đồng tiếp tục trò chuyện.</PageIntro>
    <div className="feature-stories">
      <section className="feature-story">
        <div className="feature-story-copy"><span className="eyebrow lime">01 / KẾT NỐI HỘI THOẠI</span><h2>Nhiều chuyện cùng lúc.<br />Vẫn tìm được nhau.</h2><p>Một kênh Discord có thể có nhiều cuộc trò chuyện đan xen. Coconerd dựa vào ngữ cảnh và các lượt trả lời để kết nối những tin nhắn cùng chủ đề.</p><p>Khi câu chuyện quay lại, bot có thể tiếp nối mạch cũ. Tin nhắn gốc vẫn ở nơi bạn đã gửi.</p><a href="#/demo/topics/a-little-garden" className="text-link">Mở một chủ đề mẫu <ArrowUpRight size={17} /></a></div>
        <div className="feature-visual topic-visual"><div className="visual-caption"><span><Hash size={14} />góc-chung</span><span>MINH HỌA</span></div><div className="sample-chat"><p><span className="sample-person">L</span><span><strong>Linh</strong>Cuối tuần mình làm website nhé?</span></p><p><span className="sample-person sample-person-olive">A</span><span><strong>An</strong>Có playlist nào để làm việc không?</span></p><p><span className="sample-person">M</span><span><strong>Minh</strong>Mình có vài ý tưởng về bố cục.</span></p></div><div className="topic-branches"><div><MessageCircle size={17} /><span>Website mới<small>Linh · Minh</small></span><span className="branch-dot" /></div><div><Leaf size={17} /><span>Playlist cuối tuần<small>An</small></span><span className="branch-dot" /></div></div><span className="visual-footnote">Một kênh chung. Những mạch trò chuyện riêng.</span></div>
      </section>
      <section className="feature-story feature-story-reverse">
        <div className="feature-story-copy"><span className="eyebrow lime">02 / BẮT KỊP CÂU CHUYỆN</span><h2>Rời bàn phím một chút.<br />Quay lại vẫn theo kịp.</h2><p>Bản tóm tắt giữ lại ý chính, những điều đã thống nhất và câu hỏi còn mở. Bạn biết câu chuyện đang ở đâu trước khi đọc sâu hơn.</p><p>Tóm tắt là điểm bắt đầu. Với thông tin quan trọng, luôn đối chiếu lại tin nhắn gốc.</p><a href="#/demo/topics/new-website" className="text-link">Đọc thử một bản tóm tắt <ArrowUpRight size={17} /></a></div>
        <div className="feature-visual summary-visual"><div className="visual-caption"><span><Sparkles size={15} />Góc ý tưởng: website mới</span><span>MINH HỌA</span></div><span className="summary-kicker">CÂU CHUYỆN ĐẾN LÚC NÀY</span><h3>Một ngôi nhà nhỏ,<br />gần với thiên nhiên.</h3><p>Cả nhóm đang tìm hướng thiết kế cho website mới của Coconerd.</p><ul><li><Check size={14} />Màu kem và nền tối, lấy cảm hứng từ khu vườn.</li><li><Check size={14} />Chuyển động nhẹ, giữ nội dung dễ đọc.</li></ul><div className="summary-open-question"><span>CÒN ĐANG BÀN</span>Những chi tiết tương tác nào nên có?</div><span className="visual-footnote">Ý chính để đọc nhanh. Tin gốc để đối chiếu.</span></div>
      </section>
      <section className="feature-story">
        <div className="feature-story-copy"><span className="eyebrow lime">03 / CHĂM CHÚT ĐÚNG CHỖ</span><h2>Khu vườn của bạn.<br />Ranh giới do bạn chọn.</h2><p>Quản trị viên quyết định server và những kênh bot được phép tiếp nhận tin. Có thể tạm dừng nhận tin khi cần.</p><p>Thời gian lưu trữ được cấu hình theo cộng đồng; dữ liệu hết hạn được dọn theo thiết lập đó.</p><a href="#/privacy" className="text-link">Xem cách dữ liệu được xử lý <ArrowUpRight size={17} /></a></div>
        <div className="feature-visual channels-visual"><div className="visual-caption"><span><ShieldCheck size={15} />Phạm vi hoạt động</span><span>MINH HỌA</span></div><h3>Chỉ lắng nghe<br />những nơi được chọn.</h3><div className="sample-channel"><Hash size={18} /><span>góc-chung</span><span><Check size={13} />Được chọn</span></div><div className="sample-channel"><Hash size={18} /><span>ý-tưởng</span><span><Check size={13} />Được chọn</span></div><div className="sample-channel channel-private"><LockKeyhole size={17} /><span>chuyện-riêng</span><span>Ngoài phạm vi</span></div><span className="visual-footnote"><Leaf size={14} />Phạm vi và thời gian lưu do quản trị viên quyết định.</span></div>
      </section>
    </div>
    <div className="public-next"><p>Chạm thử vào một cuộc trò chuyện.</p><a className="pill" href="#/demo">Mở bản trải nghiệm <ArrowUpRight size={16} /></a></div>
  </PublicLayout>;
}

function HelpAvailability() {
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [errors, setErrors] = useState({ links: '', status: '' });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setConfig(null); setStatus(null); setErrors({ links: '', status: '' });
    void request<SiteConfig>('/api/site').then(result => { if (active) setConfig(result); }).catch(cause => { if (active) setErrors(current => ({ ...current, links: errorMessage(cause) })); });
    void request<PublicStatus>('/api/status').then(result => { if (active) setStatus(result); }).catch(cause => { if (active) setErrors(current => ({ ...current, status: errorMessage(cause) })); });
    return () => { active = false; };
  }, [revision]);
  const labels = { ok: 'Dịch vụ đang sẵn sàng', degraded: 'Một phần dịch vụ cần chú ý', unavailable: 'Chưa nhận được phản hồi', unconfigured: 'Trạng thái bot chưa được công bố' };
  const componentLabels = { ok: 'hoạt động', unavailable: 'không sẵn sàng', unknown: 'chưa xác minh' };
  return <section className="help-contact" id="help-contact"><div className="help-contact-heading"><span className="eyebrow lime">03 / KHI BẠN CẦN THÊM</span><button className="icon-button" onClick={() => setRevision(n => n + 1)} aria-label="Làm mới thông tin hỗ trợ và trạng thái"><RefreshCw size={15} /></button></div><div className="help-contact-grid">
    <article><MessageCircle size={23} strokeWidth={1.4} /><h2>Cần một chút trợ giúp?</h2>{errors.links ? <p role="alert">{errors.links}</p> : !config ? <p role="status">Đang kiểm tra kênh hỗ trợ…</p> : config.supportUrl ? <><p>Ghé server hỗ trợ chính thức để trao đổi cùng cộng đồng.</p><a className="text-link" href={config.supportUrl} target="_blank" rel="noreferrer">Mở server hỗ trợ <ArrowUpRight size={16} /></a></> : <p>Kênh hỗ trợ chính thức đang được chuẩn bị. Bạn có thể bắt đầu với các câu hỏi ở trên hoặc thử một cuộc trò chuyện mẫu.</p>}</article>
    <article><Leaf size={23} strokeWidth={1.4} /><h2>Khu vườn hôm nay</h2>{errors.status ? <p role="alert">{errors.status}</p> : !status ? <p role="status">Đang kiểm tra trạng thái…</p> : <><p className={`help-service-state ${status.status === 'ok' ? 'state-ok' : ''}`}><span />{labels[status.status]}</p>{status.status !== 'unconfigured' && <><p className="small-note">Lưu trữ: {componentLabels[status.database]}. Xử lý chủ đề: {componentLabels[status.worker]}.</p><p className="small-note">Kiểm tra lúc {new Date(status.checkedAt).toLocaleString('vi-VN')}. Không xác nhận kết nối Discord.</p></>}</>}</article>
  </div></section>;
}

function Guide() {
  const [query, setQuery] = useState('');
  const reduced = useReducedMotion();
  const items = faqs.filter(item => matchesText(`${item.question} ${item.answer}`, query));
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' });
  return <PublicLayout active="/guide" title="Hướng dẫn & giải đáp">
    <PageIntro eyebrow="HƯỚNG DẪN & GIẢI ĐÁP" title={<>Bắt đầu với<br /><em>Coconerd.</em></>}>Các bước đầu tiên cho server, câu trả lời cho những thắc mắc thường gặp và một nơi để tìm hỗ trợ.</PageIntro>
    <nav className="help-jump-links" aria-label="Nội dung hướng dẫn"><button onClick={() => jump('help-start')}>Bắt đầu <ArrowDown size={13} /></button><button onClick={() => jump('help-questions')}>Câu hỏi thường gặp <ArrowDown size={13} /></button><button onClick={() => jump('help-contact')}>Hỗ trợ & trạng thái <ArrowDown size={13} /></button></nav>
    <section className="help-start" id="help-start"><span className="eyebrow lime">01 / CHO SERVER CỦA BẠN</span><h2>Ba bước, rồi cứ trò chuyện thôi.</h2><div className="help-steps">
      <article><span className="help-step-number">01</span><h3>Thêm một người bạn.</h3><p>Khi lời mời chính thức được mở, chọn server bạn có quyền quản lý để thêm Coconerd.</p><a href="#/invite" className="text-link">Kiểm tra lời mời <ArrowUpRight size={15} /></a></article>
      <article><span className="help-step-number">02</span><h3>Chọn nơi bot lắng nghe.</h3><p>Quản trị viên cho phép các kênh cần xử lý và thông báo phạm vi này cho thành viên.</p><a href="#/privacy" className="text-link">Tìm hiểu về dữ liệu <ArrowUpRight size={15} /></a></article>
      <article><span className="help-step-number">03</span><h3>Trò chuyện như mọi ngày.</h3><p>Coconerd kết nối các tin liên quan. Khi quay lại, đọc chủ đề và tóm tắt để bắt kịp.</p><a href="#/demo" className="text-link">Thử trong không gian mẫu <ArrowUpRight size={15} /></a></article>
    </div></section>
    <section className="help-faq" id="help-questions"><div className="help-faq-heading"><span className="eyebrow lime">02 / CÂU HỎI THƯỜNG GẶP</span><h2>Bạn đang thắc mắc<br />điều gì?</h2><label className="public-search"><Search size={17} /><input aria-label="Tìm câu hỏi…" placeholder="Tìm câu hỏi…" value={query} onChange={event => setQuery(event.target.value)} />{query && <button onClick={() => setQuery('')} aria-label="Xóa tìm kiếm">×</button>}</label><p className="result-count" aria-live="polite">{items.length} câu trả lời</p></div><div className="public-faq">{items.length ? items.map(item => <details key={item.question} open={query.trim() ? true : undefined}><summary>{item.question}<ChevronDown size={17} /></summary><p>{item.answer}</p></details>) : <div className="public-empty"><p>Chưa tìm thấy câu trả lời phù hợp.</p><button className="text-link" onClick={() => setQuery('')}>Xem tất cả câu hỏi <ArrowRight size={15} /></button></div>}</div></section>
    <HelpAvailability />
  </PublicLayout>;
}

function Privacy() {
  return <PublicLayout active="/privacy" title="Dữ liệu & riêng tư"><PageIntro eyebrow="PHẠM VI RÕ RÀNG, LỰA CHỌN CÓ CHỦ ĐÍCH" title={<>Dữ liệu &<br /><em>quyền riêng tư.</em></>}>Coconerd xử lý những gì, ở đâu và trong bao lâu. Đây là những điều cộng đồng của bạn cần biết.</PageIntro><div className="privacy-article">{[
    ['Chỉ những kênh được chọn', 'Hệ thống tiếp nhận tin từ server đã bật và những kênh được cho phép. Quản trị viên lựa chọn phạm vi này và có thể tạm dừng việc nhận tin. Luồng tích hợp hiện có không xử lý tin nhắn riêng.'],
    ['Nội dung được lưu', 'Dữ liệu hội thoại gồm ID server, kênh, tin nhắn và tác giả; tên hiển thị, nội dung, thời gian và liên kết trả lời. Chủ đề, tóm tắt và tác vụ cho bot được giữ để tiếp nối cuộc trò chuyện.'],
    ['AI và ngữ cảnh', 'Khi sử dụng model thật, nội dung cùng ngữ cảnh được chọn được gửi tới dịch vụ AI Meta đã cấu hình. Quản trị viên cần chọn kênh phù hợp và thông báo cách xử lý cho thành viên. Tóm tắt có thể chưa đầy đủ; hãy đối chiếu với tin gốc.'],
    ['Thời gian lưu trữ', 'Quản trị viên có thể cấu hình thời gian giữ tin từ 1 đến 3.650 ngày. Tiến trình xử lý sẽ dọn dữ liệu hết hạn. Thành viên nên liên hệ quản trị viên server để biết cấu hình đang áp dụng.'],
    ['Website và bản trải nghiệm', 'Website không yêu cầu tài khoản và không hiển thị hội thoại riêng của server Discord. Nội dung trong bản trải nghiệm là minh họa; những thay đổi được lưu cục bộ trong trình duyệt và có thể đặt lại. Website dùng Google Fonts để hiển thị kiểu chữ; không tích hợp quảng cáo hay công cụ analytics.'],
  ].map(([title, copy], index) => <section key={title}><span>0{index + 1}</span><div><h2>{title}</h2><p>{copy}</p></div></section>)}</div></PublicLayout>;
}

export default function PublicPages({ route }: { route: string }) {
  if (route === '/features') return <Features />;
  if (route === '/guide') return <Guide />;
  if (route === '/privacy') return <Privacy />;
  return <PublicLayout active="" title="Không tìm thấy"><div className="public-empty"><Flower size={64} /><h1>Lạc vào một góc vườn?</h1><p>Trang này chưa tồn tại.</p><a className="pill" href="#/">Về trang chủ <ArrowRight size={16} /></a></div></PublicLayout>;
}
