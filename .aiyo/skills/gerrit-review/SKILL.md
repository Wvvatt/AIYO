---
name: gerrit-review
description: Perform code reviews on Gerrit changes using gerrit_cli. Use when reviewing code changes, examining diffs, or providing feedback on Gerrit submissions. Covers security, performance, design, and test coverage review.
---

# Gerrit Code Review

Review Gerrit code changes using `gerrit_cli` tool.

## Review Workflow

### 1. Get Change from User

If change_id not provided in the request, ask the user:
- "请提供要审查的 Gerrit Change ID 或 URL"
- "例如: 634172 或 https://gerrit.example.com/c/634172"

Then ask for patch set (optional):
- "要审查哪个版本? (默认 current)"
- "输入 patch set 数字，或直接回车使用最新版本"

### 2. Fetch Change Information

```python
change = gerrit_cli("get_change", {"change_id": 634172})
detail = gerrit_cli("get_change_detail", {"change_id": 634172})
diff = gerrit_cli("get_change_diff", {"change_id": 634172, "revision": revision})
```

### 3. Review Checklist

**Identifying Problems**
- Runtime errors: null pointers, exceptions, resource leaks
- Performance: unbounded loops, unnecessary allocations, inefficient algorithms
- Side effects: unintended changes to other components
- Backwards compatibility: breaking API changes
- Security: injection risks, secrets exposure, access control

**Design Assessment**
- Do component interactions make sense?
- Does the change align with existing architecture?
- Are there conflicts with project goals?

**Test Coverage**
- Are new features tested?
- Do tests cover edge cases?
- Are error paths tested?

**Long-Term Impact**
Flag for senior review when changes involve:
- Database schema changes
- API contract modifications
- Security-critical code
- Performance-critical paths

### 4. Generate Review Report

Summarize findings with:
- Change overview (title, author, files changed)
- Key issues found (with file paths and line numbers)
- Suggestions for improvement
- Proposed vote (+2, +1, -1, or -2)

### 5. Confirm Before Submitting (Optional)

If user asks to submit review, **confirm both votes before proceeding**:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📤 即将提交审查意见
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Change: {change_number} - {subject}

Code-Review: {code_review_vote} (-2/-1/0/+1/+2)
Verified: {verified_vote} (-1/0/+1)

评论内容:
{review_message}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
是否确认提交? [Y/n]
```

**Ask for votes if not specified**:
- "Code-Review 投票? (+2=批准, +1=看起来不错, -1=需要修改, -2=拒绝, 0=无意见)"
- "Verified 投票? (+1=验证通过, -1=验证失败, 0=未验证)"

Wait for user confirmation before calling `set_review`.

**If user confirms**:
```python
gerrit_cli("set_review", {
    "change_id": change_id,
    "message": review_comment,
    "code_review": code_review_vote,    # -2, -1, 0, +1, +2
    "verified": verified_vote            # -1, 0, +1
})
```

**If user declines**:
- Allow editing the message or votes
- Or skip submitting and keep as draft review

## Feedback Guidelines

**Tone**
- Be polite and empathetic
- Provide actionable suggestions
- Phrase uncertainties as questions: "Have you considered...?"

**Approval**
- Approve when only minor issues remain
- Don't block for stylistic preferences
- Goal is risk reduction, not perfect code

## Common Patterns to Flag

### C/C++

```c
// Bad: No null check
char *buf = malloc(size);
strcpy(buf, data);  // Crash if malloc fails

// Good: Check allocation
char *buf = malloc(size);
if (!buf) return -ENOMEM;
strcpy(buf, data);
```

```c
// Bad: Buffer overflow
char buf[10];
sprintf(buf, "long string: %s", input);  // Overflow risk

// Good: Use safe functions
snprintf(buf, sizeof(buf), "long string: %s", input);
```

### Python

```python
# Bad: No exception handling
result = risky_operation()

# Good: Handle exceptions
try:
    result = risky_operation()
except SpecificError as e:
    log.error(f"Operation failed: {e}")
    return None
```

### Security

```c
// Bad: Command injection
system(user_input);  // Dangerous!

// Good: Validate and sanitize
if (!is_valid_filename(user_input)) {
    return -EINVAL;
}
```

## References

- Review templates: [references/report-template.md](references/report-template.md)
- gerrit_cli commands: [references/commands.md](references/commands.md)
