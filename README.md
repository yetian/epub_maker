# txt2epub

将中文 TXT 小说转换为 EPUB 的命令行工具。

## 功能

- **自动识别编码**：依次检查 BOM、UTF-8、`charset_normalizer`、`chardet` 及常见中文编码（GB18030 / GBK / Big5 等）。当结果不确定时，会列出候选编码、显示预览并让用户选择，也可手动输入编码名。
- **统一输出 UTF-8**：非 UTF-8 内容解码后由 EPUB 写入器统一输出为 UTF-8。
- **章节识别**：
  - `第一章`、`第1章`、`第一百二十三回`（章 / 回 / 节 / 集 / 卷 / 部 / 篇）
  - 单独的数字行，如 `1`、`12.`、`（3）`、`1、标题`
  - 关键词标题：`前言`、`楔子`、`序言`、`序`、`推荐`、`后记`、`番外`、`感言` 等
  - 章节标题可写在同一行，也可在下一行（当标题行只有「第X章」时自动合并）
- **前言处理**：第一个可识别章节之前的内容会作为一个名为「标题」的章节。
- **分段规则**：章节正文按 TXT 中的换行分段，每个非空行生成一个段落。
- **目录**：按识别出的章节自动生成 EPUB 目录（TOC）。

## 依赖

- Python 3.10+
- [EbookLib](https://github.com/aerkalov/ebooklib)
- [charset-normalizer](https://github.com/Ousret/charset_normalizer)
- [chardet](https://github.com/chardet/chardet)

安装：

```bash
pip install EbookLib charset-normalizer chardet
```

## 使用方法

```bash
# 基本用法，输出为同名 .epub
python3 txt2epub.py example.txt

# 指定输出路径与作者
python3 txt2epub.py input.txt -o output.epub --author "佚名"

# 强制指定输入编码（跳过自动检测）
python3 txt2epub.py input.txt -e gb18030

# 不确定时不交互，直接采用最佳猜测
python3 txt2epub.py input.txt --no-interactive

# 指定书名（默认取文件名）
python3 txt2epub.py input.txt --title "示例小说"
```

### 参数

| 参数 | 说明 |
| --- | --- |
| `input` | 输入的 `.txt` 文件 |
| `-o, --output` | 输出的 `.epub` 路径，默认与输入同名 |
| `-e, --encoding` | 强制输入编码，跳过自动检测 |
| `--author` | 作者，默认 `Unknown` |
| `--title` | 书名，默认取输入文件名 |
| `--no-interactive` | 编码不确定时不询问，直接使用最佳猜测 |

## 章节识别说明

脚本逐行扫描，命中以下规则的行被视为章节标题：

1. `第[数字]+[章回节集卷部篇]`，其后可跟章节名；
2. 单独的数字行或数字加短标题；
3. 关键词行（`前言`、`楔子`、`序言`、`序`、`推荐`、`后记`、`番外` 等），且整行长度不超过 30 个字符。

从当前标题行（含可合并的下一行标题）到下一个标题行之前的全部内容，即为该章正文。正文中的空行会被忽略。

## 项目结构

```
txt2epub.py   # 主脚本：编码检测 / 章节切分 / EPUB 生成
example.txt   # 示例文本，演示前言、序章、楔子、数字章节等格式
```

## 备注

仓库附带 `example.txt`，可直接运行：

```bash
python3 txt2epub.py example.txt --no-interactive
```

示例会生成 7 个章节，包括自动归入「标题」的前言部分。
