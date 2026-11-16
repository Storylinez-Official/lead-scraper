# Graphify-Labs/graphify

- Website: https://graphify.com/
- Documentation: https://docs.graphify.com/open-source/cli-quickstart
- Business type: developer API
- Source: github-developer-tools (https://github.com/Graphify-Labs/graphify)
- Lead score: **50/100** - 50 base; -15 docs scored 8/10; +5 team inbox or phone; +10 developer product, docs drive adoption

## Summary

The Graphify documentation provides clear, step-by-step CLI instructions and thorough installation and setup workflows, supported by good navigation and search features. However, it lacks detailed explanations for some commands and concepts, comprehensive API references, and robust error handling guidance. Adding these elements would significantly enhance usability, especially for novice users and developers seeking deeper technical insights.

## Documentation scores

| Dimension | Score | Why |
|---|---|---|
| Quality | 8/10 | The documentation is generally clear with well-structured step-by-step instructions, concrete CLI examples, and explanations of commands and flags. The CLI quickstart and MCP server quickstart pages provide detailed command usage and expected outputs. However, some commands and concepts (e.g., 'graphify cluster-only', 'god-nodes') could benefit from more detailed explanations or examples for novice users. |
| Completeness | 7/10 | The sample covers installation, CLI usage, skill integration, MCP server setup, Docker deployment, and advanced usage like vibe coding. However, it lacks explicit error handling sections beyond brief troubleshooting tips, no changelog or versioning info is seen, and no comprehensive API reference or detailed explanation of graph internals is present. |
| Usability | 8/10 | The docs have a sidebar TOC, search functionality, and consistent navigation links. The pages are well segmented with headings and code blocks. The presence of 'What’s next' sections guides users to related topics. Some pages could improve discoverability of advanced features by linking more explicitly from quickstart pages. |
| **Overall** | **8/10** | developer API guide with CLI and server setup |

### Strengths

- Clear step-by-step CLI instructions with examples
- Good coverage of installation and setup workflows
- Includes troubleshooting tips and next steps guidance
- Well-structured navigation and search support

### Weaknesses

- Limited explanation of some commands and flags for beginners
- No comprehensive API reference or detailed graph data model
- Sparse error handling and recovery guidance
- No changelog or version history visible

### Missing sections

- Comprehensive API reference
- Detailed error codes and troubleshooting guide
- Changelog or release notes
- In-depth explanation of graph data structures and internals

## Recommended improvements

1. **[high] Command explanations**: Some commands and concepts like 'graphify cluster-only' and 'god-nodes' are insufficiently explained for beginners. -> Add detailed descriptions and practical examples for these commands to improve understanding and usability for new users.
2. **[high] API reference**: No comprehensive API reference or detailed explanation of the graph data model is present. -> Develop a complete API reference section and include in-depth documentation on graph internals and data structures to support advanced users and integration efforts.
3. **[medium] Error handling**: Sparse error handling and recovery guidance beyond brief troubleshooting tips. -> Introduce a dedicated error codes and troubleshooting guide section to help users diagnose and resolve issues more effectively.
4. **[medium] Changelog and versioning**: No changelog or release notes are visible in the documentation. -> Add a changelog or release notes section to keep users informed about updates, fixes, and new features.
5. **[low] Feature discoverability**: Advanced features are not always easily discoverable from quickstart pages. -> Enhance linking from quickstart and introductory pages to advanced topics to improve feature discoverability.

## Contacts

- founders@graphify.com
- careers@graphify.com
- support@graphify.com

## Outreach opener

**Subject:** Improving clarity and depth in Graphify docs

I reviewed the Graphify documentation and noticed that while the CLI quickstart is clear and well-structured, some commands like 'graphify cluster-only' and concepts such as 'god-nodes' could use more detailed explanations or examples. Also, the docs currently lack a comprehensive API reference and detailed error handling guidance, which might be valuable for developers integrating deeply with your platform. If you're exploring ways to enhance these areas, I'd be interested in sharing some insights.

## Evidence

- Doc discovery score 12: +2 code_blocks (12); +1 many_code_blocks; +2 install_command; +1 doc_headings (configuration); +2 doc_url; +3 doc_platform (mintlify); +1 sidebar_toc
- Pages sampled: 8, code blocks: 62, languages: none detected, search: True
  - CLI quickstart: build and query a code graph - Graphify: https://docs.graphify.com/open-source/cli-quickstart
  - Graphify CLI: open-source code knowledge graph - Graphify: https://docs.graphify.com/open-source/overview
  - Quickstart: map a repository with the skill - Graphify: https://docs.graphify.com/open-source/quickstart
  - Install Graphify CLI with uv or pipx - Graphify: https://docs.graphify.com/open-source/installation
  - MCP server quickstart: serve your graph - Graphify: https://docs.graphify.com/open-source/mcp-server
  - Self-host the Graphify MCP server with Docker - Graphify: https://docs.graphify.com/open-source/self-host
  - Vibe coding with Graphify CLI - Graphify: https://docs.graphify.com/open-source/vibe-coding
  - Run Graphify locally - Graphify: https://docs.graphify.com/open-source/local-development
