import React from "react";

const SIFT_ASSET_WEB_URL =
  "https://app.siftstack.com/asset/ee5a2cc0-7885-468c-a70e-9afe398354f5";

type Props = {
  assetName: string | undefined;
};

export function SiftCard({ assetName }: Props) {
  return (
    <div className="siftCard">
      <div className="siftCardLabel">Sift asset</div>
      <div className="siftCardAsset mono">{assetName ?? "—"}</div>
      <a
        className="btn siftCardLink"
        href={SIFT_ASSET_WEB_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        Open in Sift
      </a>
    </div>
  );
}
