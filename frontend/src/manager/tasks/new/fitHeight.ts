// 문장 칸 높이를 내용에 맞춘다(좁은 화면에서 긴 문장이 잘리지 않게). 줄바꿈은 넣지 않는다 — 한 줄 = 한 동작.
export function fitHeight(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  // border-box라 높이에 테두리를 더해야 글 칸(clientHeight)이 글 높이(scrollHeight)와 같아진다.
  if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
}
