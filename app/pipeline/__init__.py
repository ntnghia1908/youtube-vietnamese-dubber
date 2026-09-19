"""Stage: điều phối pipeline end-to-end (download -> ... -> render).

Checkpoint 7: ``dub.py`` (``run_dub``) — gọi thẳng các hàm stage của các
checkpoint trước theo đúng thứ tự, tự resume và tự sửa lỗi tạm thời
(dịch lỗi, thiếu audio) trong số vòng giới hạn trước khi render.

Không re-export gì ở đây: import ``dub.py`` kéo theo yt-dlp/faster-whisper,
các lệnh không cần tới ``dub`` (vd ``download`` đơn lẻ) không nên phải tải
các dependency đó.
"""
