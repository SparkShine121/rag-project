# ragdb 项目错题集

> dev-workflow 阶段六沉淀，任务开始前按相关性筛选读取。格式：`- [日期][类目][严重度] 描述。教训：…`

- [2026-09-08][流程/编排][中] 查证 GitHub 内容（OpenClaw/Hermes 的 MCP 支持）时降级链绕路：WebSearch/WebFetch 失败后未优先用环境内已有的 GitHub MCP（get_file_contents/search_code），且在已知网络受限后仍试了沙箱 curl。教训：① GitHub 内容优先走 GitHub MCP 通道；② 确认沙箱无网络后直接升级非沙箱 curl 或换通道，不做可预见的无效重试；③ "待核实"结论要记录已试渠道，穷尽低成本渠道后才搁置。
- [2026-09-08][流程/编排][低] 发现本机无 git 身份后，读取同级仓库 .git/config 推断惯例（xb-dev@local）并直接设置本仓库局部身份 rag-dev@local——虽在汇报中披露，但更优做法是事前一句话确认。教训：推断性配置（git config、环境变量、默认路径等）默认先向用户确认；至少当场在汇报中显著声明。
- [2026-09-08][工具使用][中] 用 Edit 整段替换 Markdown 表格时凭记忆重建文本，漏掉原有 ChatGPT 行（下一步自愈补回）。教训：① 结构化内容（表格/列表）用行级锚点编辑，避免整段重写；② 必须整段替换时，替换后立即重读并比对关键行/行数。
- [2026-09-08][工具使用][中] `git add -A` 未审查暂存区，3 个 macOS 系统垃圾文件（.DS_Store）被提交入库，且当时仓库无 .gitignore。教训：① .gitignore 先于首次 add 建好；② 提交前 git status / git ls-files 逐项确认；③ add 用具体文件名而非 -A/.。
