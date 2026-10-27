#!/bin/sh
# Install dsh-purge 0.2.1-rc.2 adapted build into the DSH web profile.
# Downloads the latest (or pinned) release, verifies SHA256, backs up, installs.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/qianbkk/dsh-purge-priv/main/scripts/install.sh | sh
#   PURGE_VERSION=1.1.72-dsh021rc2.5 sh install.sh
#   DSH_HOME=/custom/.dsh sh install.sh
set -eu

REPO="qianbkk/dsh-purge-priv"
VERSION="${PURGE_VERSION:-}"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
DEST="$DSH_HOME/profiles/web/node_modules"
TARGET="$DEST/dsh-purge"

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "需要 curl"
[ -d "$DEST" ] || die "找不到 profile 目录：$DEST（先用 dsh web 启动一次）"

if [ -z "$VERSION" ]; then
  say "→ 查询最新发行版…"
  VERSION=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' | head -1)
  [ -n "$VERSION" ] || die "无法确定最新版本，可显式指定 PURGE_VERSION"
fi

BASE="https://github.com/$REPO/releases/download/v$VERSION"
TGZ="dsh-purge-$VERSION.tgz"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

say "→ 下载 $TGZ"
curl -fsSL "$BASE/$TGZ" -o "$TMP/$TGZ" || die "下载失败：$BASE/$TGZ"
curl -fsSL "$BASE/SHA256SUMS.txt" -o "$TMP/SHA256SUMS.txt" || die "校验文件下载失败"

say "→ 校验 SHA256"
(cd "$TMP" && grep " $TGZ\$" SHA256SUMS.txt > sums.txt && shasum -a 256 -c sums.txt >/dev/null) \
  || die "SHA256 校验失败"

if [ -d "$TARGET" ]; then
  BAK="$TARGET.$(date +%Y%m%d-%H%M%S).bak"
  say "→ 备份现有插件到 $BAK"
  mv "$TARGET" "$BAK"
fi

mkdir -p "$TARGET"
tar xzf "$TMP/$TGZ" -C "$TARGET" --strip-components=1

# 写版本戳：避免宿主启动时认为版本落后而反复重打补丁
python3 - "$VERSION" <<'PY'
import json, os, sys, datetime
version = sys.argv[1]
home = os.path.join(os.path.expanduser('~'), '.dsh', 'dsh-purge')
os.makedirs(home, exist_ok=True)
sha = f'apply:{version}'
open(os.path.join(home, 'installed-rev'), 'w').write(sha + '\n')
json.dump({'version': version, 'sha': sha,
           'at': datetime.datetime.now(datetime.UTC).isoformat().replace('+00:00', 'Z')},
          open(os.path.join(home, 'applied.json'), 'w'), indent=2)
PY

say "✓ 已安装 dsh-purge $VERSION → $TARGET"
say "  完全退出并重开 DSH；打开 Purge 面板点「应用」"
