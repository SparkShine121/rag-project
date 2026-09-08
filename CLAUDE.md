# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

本项目（RAG 项目）处于初始化阶段，尚无代码。待项目结构成型后，请补充以下章节：构建/测试/运行命令、代码架构说明。

## 开发流程约束

本项目安装了项目级 skill：`.claude/skills/dev-workflow/`。凡在本项目进行功能开发、bug 修复、代码维护等编码任务，必须按该 skill 定义的六阶段闭环流程执行（需求拷问 → 设计探索 → 计划拆分 → TDD 实现 → 收尾整理 → 自进化）。

## 证据先于断言（强化，用户 2026-09-08 指定）

- 任何"完成/通过/修复"声明前，必须有**本回合新鲜运行**的验证命令及输出。
- 测试/构建/lint 命令一律先 `set -o pipefail`，禁止让管道尾命令（`| tail` 等）掩盖退出码。
- GREEN 验证与提交必须在同一 `&&` 命令链内完成，链中任何一步失败即停止，不得带病提交。
- 提交前 `git status --short` 确认无未跟踪的实现文件残留。
