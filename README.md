# 苏大制度政策 Agent

作者：王妍

这是一个面向苏州大学制度政策问答的 agent 项目。项目包含两个入口：

- 本地完整版本：运行 Python 后端，支持知识库入库、上传文件、官网同步和问答。
- GitHub Pages 静态版本：放在 `docs/` 目录，可发布到 GitHub 后随时打开网页，适合基础检索和分流建议。

## 本地完整版本

```powershell
python app.py
```

启动后访问：

```text
http://127.0.0.1:8765
```

本地版功能：

- 上传制度文件并建立本地索引。
- 检索制度依据，生成规范答复。
- 根据问题类型推荐可能的网站、部门或老师类型。
- 同步苏州大学官网、规章制度站和财务处官网中的制度、办法、规定、细则、通知等官方文件。

## GitHub Pages 静态版本

静态网页位于：

```text
docs/index.html
```

这个版本可以直接用浏览器打开，也可以通过 GitHub Pages 发布。它不需要 Python 后端，但也不能执行本地版的上传入库、官网同步、PDF/Word 解析等服务端功能。

发布方式：

1. 把本项目推送到 GitHub 仓库。
2. 进入 GitHub 仓库页面，打开 `Settings` → `Pages`。
3. 在 `Build and deployment` 中选择 `Deploy from a branch`。
4. Branch 选择 `main`，文件夹选择 `/docs`。
5. 保存后等待 GitHub 生成访问链接。

## 推荐推送命令

如果仓库还没有初始化：

```powershell
git init
git branch -M main
git add .
git commit -m "Publish Suda policy agent"
git remote add origin https://github.com/827285406-commits/-.git
git push -u origin main
```

如果已经初始化过，只需：

```powershell
git add .
git commit -m "Update Suda policy agent"
git push
```

## 文件说明

- `app.py`：本地 HTTP 服务入口。
- `static/`：本地完整版本网页。
- `docs/`：GitHub Pages 静态网页。
- `suda_policy_agent/`：制度检索、文档解析和答复逻辑。
- `config/`：官网抓取源和分流规则。
- `knowledge/`：本地知识库文件。
- `data/`：本地生成的索引、上传文件和运行数据。

## 注意

公开发布到 GitHub 前，请确认仓库里没有不适合公开的制度附件、个人信息、日志或浏览器缓存。本项目已用 `.gitignore` 排除常见的本地上传文件、索引、日志和浏览器缓存。
