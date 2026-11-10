// QR 코드(기기 연결 주소). qrcode-generator로 칸을 계산해 SVG 사각형으로 그린다(외부 요청·그림 파일 없음).
import { useMemo } from "react";
import qrcode from "qrcode-generator";

export default function QrCode({ text, size = 160, label }: { text: string; size?: number; label: string }) {
  const { n, path } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const count = qr.getModuleCount();
    let d = "";
    for (let r = 0; r < count; r++) {
      for (let c = 0; c < count; c++) if (qr.isDark(r, c)) d += `M${c + 4} ${r + 4}h1v1h-1z`;
    }
    return { n: count + 8, path: d };
  }, [text]);
  return (
    <svg
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${n} ${n}`}
      shapeRendering="crispEdges"
      className="shrink-0 rounded-control border border-paper-200 bg-white"
      data-testid="qr-code"
    >
      <rect width={n} height={n} fill="#FFFFFF" />
      <path d={path} fill="#000000" />
    </svg>
  );
}
