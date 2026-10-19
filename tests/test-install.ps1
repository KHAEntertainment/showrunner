$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$installer = Join-Path $repo "install.ps1"
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("claude-dev-install-" + [guid]::NewGuid())
$passCount = 0
# The installer links "$env:USERPROFILE\.agents\skills\dev" by default. Point
# USERPROFILE at a scratch directory for the whole suite so no case can touch
# the real ~/.agents (or ~/.claude); cases that assert on the link use their
# own home. The original value is restored in the finally block.
$originalUserProfile = $env:USERPROFILE
$suiteHome = Join-Path $testRoot "home"
$onWindowsHost = ($PSVersionTable.PSEdition -eq "Desktop") -or ($IsWindows -eq $true)
$linkKind = if ($onWindowsHost) { "Junction" } else { "SymbolicLink" }

function Assert-Path([string]$Path) {
    if (-not (Test-Path $Path)) { throw "Missing path: $Path" }
}
function Assert-Absent([string]$Path) {
    if (Test-Path $Path) { throw "Unexpected path: $Path" }
}
# Each case starts with no discovery link under the suite home, so cases that
# do not assert on the link never see a leftover from the previous one.
function Reset-SuiteLink {
    $suiteLink = Join-Path $suiteHome ".agents\skills\dev"
    $suiteLinkItem = Get-Item -LiteralPath $suiteLink -Force -ErrorAction SilentlyContinue
    if ($suiteLinkItem -and $suiteLinkItem.LinkType) { $suiteLinkItem.Delete() }
    Remove-Item -LiteralPath (Join-Path $suiteHome ".agents") -Recurse -Force -ErrorAction SilentlyContinue
}
function Pass([string]$Name) {
    $script:passCount++
    Write-Host "PASS: $Name"
    Reset-SuiteLink
}
# Runs the installer, capturing the success, warning, and information streams
# as one string, so a test can assert on what was reported.
function Invoke-InstallerText([hashtable]$InstallerArguments) {
    (& $installer @InstallerArguments 3>&1 6>&1 | Out-String)
}
# Home for one case: a fresh directory, exported as USERPROFILE.
function Use-CaseHome([string]$Name) {
    $caseHome = Join-Path $testRoot $Name
    New-Item -ItemType Directory -Force -Path $caseHome | Out-Null
    $env:USERPROFILE = $caseHome
    $caseHome
}
function Get-StampedRoot([string]$SkillsParent) {
    Join-Path (Resolve-Path -LiteralPath $SkillsParent).ProviderPath "dev"
}
# Asserts the installed Skill at $Root has no literal variable left and that
# every path stamped as "$Root/<relpath>" names an existing file or directory.
function Assert-Stamped([string]$Root) {
    $checked = 0
    $pattern = [regex]::Escape($Root) + '((?:/[A-Za-z0-9_.-]+)*)'
    foreach ($skillFile in Get-ChildItem -LiteralPath $Root -Recurse -File -Force) {
        $text = [IO.File]::ReadAllText($skillFile.FullName)
        if ($text.Contains('${CLAUDE_SKILL_DIR}')) { throw "Literal variable remains in $($skillFile.FullName)" }
        foreach ($match in [regex]::Matches($text, $pattern)) {
            $checked++
            $stampedRel = $match.Groups[1].Value.TrimEnd(".")
            if (-not (Test-Path -LiteralPath ($Root + $stampedRel))) { throw "Stamped path does not exist: $Root$stampedRel" }
        }
    }
    if ($checked -eq 0) { throw "No stamped paths found under $Root" }
}
function Get-LinkTarget([string]$LinkPath) {
    $linkItem = Get-Item -LiteralPath $LinkPath -Force -ErrorAction SilentlyContinue
    if (-not ($linkItem -and $linkItem.LinkType)) { return $null }
    [string](@($linkItem.Target)[0])
}
function New-TestLink([string]$LinkPath, [string]$LinkTarget) {
    New-Item -ItemType Directory -Force -Path (Split-Path $LinkPath -Parent) | Out-Null
    New-Item -ItemType $linkKind -Path $LinkPath -Value $LinkTarget | Out-Null
}
function Skip([string]$Name, [string]$Reason) {
    Write-Host "SKIP: $Name ($Reason)"
}
# Builds a scratch PATH carrying delegating shims for the named tools
# (skipping any not found), so a test can prove "X is unavailable" while
# every other tool stays fully functional. Shims - not copies of the
# resolved executable - are used deliberately: Git for Windows' git.exe
# depends on sibling directories at its real install location (its own
# usr/bin, mingw64/bin, libexec/git-core), so relocating just the .exe
# breaks it outright rather than merely hiding it, which would make a
# test relying on git actually working misreport that breakage as
# whatever guard it meant to exercise.
function New-ScratchPathWithout([string]$Destination, [string[]]$ToolNames) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($toolName in $ToolNames) {
        $toolCmd = Get-Command $toolName -ErrorAction SilentlyContinue
        if (-not ($toolCmd -and $toolCmd.Source -and (Test-Path $toolCmd.Source -PathType Leaf))) {
            continue
        }
        $realPath = $toolCmd.Source
        if ($IsWindows) {
            $shimPath = Join-Path $Destination "$toolName.cmd"
            if (-not (Test-Path $shimPath)) {
                Set-Content -LiteralPath $shimPath -Encoding ASCII -Value @(
                    "@echo off"
                    "`"$realPath`" %*"
                    "exit /b %errorlevel%"
                )
            }
        }
        else {
            $shimPath = Join-Path $Destination $toolName
            if (-not (Test-Path $shimPath)) {
                Set-Content -LiteralPath $shimPath -Encoding ASCII -Value @(
                    "#!/bin/sh"
                    "exec `"$realPath`" `"`$@`""
                )
                & chmod +x $shimPath
            }
        }
    }
}
# Proves the scratch PATH's git shim actually runs a real git command
# against $RepoPath, not just that Get-Command finds it. Gates any test
# that genuinely invokes git during the install (as opposed to tests
# where git's absence is itself the point, which never reach a real git
# invocation): if construction is broken on some platform, the test must
# skip with a stated reason rather than misreport the breakage as the
# guard under test.
function Test-ScratchGitWorks([string]$ScratchPath, [string]$RepoPath) {
    $originalPath = $env:PATH
    try {
        $env:PATH = $ScratchPath
        $gitCmd = Get-Command git -ErrorAction SilentlyContinue
        if (-not $gitCmd) { return $false }
        & $gitCmd.Source -C $RepoPath rev-parse --show-prefix *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
    finally {
        $env:PATH = $originalPath
    }
}

try {
    # Nothing the caller exported may steer a case: the installer's config-dir
    # default and failure-injection hook are cleared for this suite's process,
    # and the detector case below scrubs or sets the Traycer identifiers itself.
    Remove-Item Env:CLAUDE_CONFIG_DIR, Env:DEV_INSTALL_FAIL_AT -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    New-Item -ItemType Directory -Path $suiteHome | Out-Null
    $env:USERPROFILE = $suiteHome

    $fresh = Join-Path $testRoot "fresh config"
    & $installer -ConfigDir $fresh -Lang en | Out-Null
    Assert-Path (Join-Path $fresh "skills\dev\SKILL.md")
    Assert-Path (Join-Path $fresh "skills\dev\phases\external-review.md")
    Assert-Path (Join-Path $fresh "skills\dev\phases\phase5.md")
    Assert-Path (Join-Path $fresh "skills\dev\scripts\inspect_external_reviews.py")
    Assert-Path (Join-Path $fresh "skills\dev\scripts\detect_execution_backend.py")
    Assert-Path (Join-Path $fresh "skills\dev\scripts\traycer_cli.py")
    Assert-Path (Join-Path $fresh "skills\dev\backends\contract.md")
    Assert-Path (Join-Path $fresh "skills\dev\backends\claude-native.md")
    Assert-Path (Join-Path $fresh "skills\dev\backends\traycer.md")
    Assert-Path (Join-Path $fresh "skills\dev\agents\report-back.md")
    Assert-Path (Join-Path $fresh "skills\dev\agents\reviewer.md")
    Assert-Path (Join-Path $fresh "skills\dev\templates\DEV_STATE_TEMPLATE.md")
    Pass "fresh install with path spaces"

    $dry = Join-Path $testRoot "dry run"
    & $installer -ConfigDir $dry -DryRun | Out-Null
    Assert-Absent $dry
    Pass "dry run is non-mutating"

    $invalid = Join-Path $testRoot "invalid language"
    $rejected = $false
    try { & $installer -ConfigDir $invalid -Lang zh | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw "Chinese install unexpectedly succeeded" }
    Assert-Absent $invalid
    Pass "unsupported language rejected before mutation"

    $legacy = Join-Path $testRoot "legacy config"
    New-Item -ItemType Directory -Force -Path (Join-Path $legacy "commands\dev") | Out-Null
    Set-Content -Path (Join-Path $legacy "commands\dev.md") -Value "legacy entry"
    Set-Content -Path (Join-Path $legacy "commands\dev\phase.md") -Value "legacy phase"
    & $installer -ConfigDir $legacy | Out-Null
    Assert-Path (Join-Path $legacy "skills\dev\SKILL.md")
    Assert-Absent (Join-Path $legacy "commands\dev.md")
    Assert-Absent (Join-Path $legacy "commands\dev")
    $legacyBackup = Get-ChildItem (Join-Path $legacy "backups\dev") -Filter dev.md -File -Recurse | Select-Object -First 1
    if (-not $legacyBackup) { throw "Legacy backup missing" }
    Pass "legacy migration and backup"

    $rollback = Join-Path $testRoot "rollback config"
    New-Item -ItemType Directory -Force -Path (Join-Path $rollback "skills\dev") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $rollback "commands\dev") | Out-Null
    Set-Content -Path (Join-Path $rollback "skills\dev\old.txt") -Value "old skill"
    Set-Content -Path (Join-Path $rollback "commands\dev.md") -Value "legacy entry"
    Set-Content -Path (Join-Path $rollback "commands\dev\old-phase.md") -Value "legacy phase"
    $env:DEV_INSTALL_FAIL_AT = "after-backup"
    $failed = $false
    try { & $installer -ConfigDir $rollback | Out-Null } catch { $failed = $true }
    Remove-Item Env:DEV_INSTALL_FAIL_AT -ErrorAction SilentlyContinue
    if (-not $failed) { throw "Injected failure unexpectedly succeeded" }
    Assert-Path (Join-Path $rollback "skills\dev\old.txt")
    Assert-Path (Join-Path $rollback "commands\dev.md")
    Assert-Path (Join-Path $rollback "commands\dev\old-phase.md")
    Pass "rollback after backup"

    # Dirty checkout: uncommitted edits to tracked files and ignored/untracked
    # files under skills/dev must not ship (Issue #44).
    $dirtySource = Join-Path $testRoot "dirty-source"
    New-Item -ItemType Directory -Force -Path $dirtySource | Out-Null
    Copy-Item (Join-Path $repo "*") $dirtySource -Recurse -Force
    Add-Content -Path (Join-Path $dirtySource "skills\dev\SKILL.md") -Value "`n<!-- local edit: must not ship -->"
    New-Item -ItemType Directory -Force -Path (Join-Path $dirtySource "skills\dev\scripts\__pycache__") | Out-Null
    Set-Content -Path (Join-Path $dirtySource "skills\dev\scripts\__pycache__\x.pyc") -Value "compiled"
    $dirtyTarget = Join-Path $testRoot "dirty target"
    & (Join-Path $dirtySource "install.ps1") -ConfigDir $dirtyTarget -Lang en | Out-Null
    Assert-Path (Join-Path $dirtyTarget "skills\dev\SKILL.md")
    if (Select-String -Path (Join-Path $dirtyTarget "skills\dev\SKILL.md") -Pattern "local edit: must not ship" -Quiet) {
        throw "Uncommitted edit to a tracked file shipped in the install"
    }
    Assert-Absent (Join-Path $dirtyTarget "skills\dev\scripts\__pycache__")
    Pass "dirty checkout excludes uncommitted edits and ignored files"

    # No .git source: falls back to the working-tree copy and reports tarball
    # provenance instead of a commit (Issue #44, ADR-007 tarball/libexec case).
    $nogitSource = Join-Path $testRoot "nogit-source"
    New-Item -ItemType Directory -Force -Path $nogitSource | Out-Null
    Copy-Item (Join-Path $repo "*") $nogitSource -Recurse -Force
    Remove-Item (Join-Path $nogitSource ".git") -Recurse -Force -ErrorAction SilentlyContinue
    $nogitTarget = Join-Path $testRoot "nogit target"
    # 6>&1 merges the Information stream (what Write-Host writes to) into the
    # success stream so the provenance line below can be captured.
    $nogitOutput = & (Join-Path $nogitSource "install.ps1") -ConfigDir $nogitTarget -Lang en 6>&1
    Assert-Path (Join-Path $nogitTarget "skills\dev\SKILL.md")
    if (-not ($nogitOutput -match "Installed from: no git metadata \(tarball install\)")) {
        throw "No-.git install did not report tarball provenance"
    }
    Pass "no-.git source installs via the copy path with tarball provenance"

    # A source with no .git of its own, sitting underneath an unrelated git
    # checkout, must not be misclassified as that ancestor's repo: it has to
    # install via the copy path too, not attempt (and fail) a git archive of
    # the ancestor's unrelated tree (Issue #44 follow-up).
    $nestedParent = Join-Path $testRoot "nested-parent"
    New-Item -ItemType Directory -Force -Path (Join-Path $nestedParent "nested") | Out-Null
    & git init --quiet -- $nestedParent
    # -c user.name/user.email keep this fixture hermetic: a CI runner with
    # no git identity configured (no ~/.gitconfig, no GECOS full name)
    # otherwise fails this commit with "Please tell me who you are."
    & git -c user.name=test -c user.email=test@example.com `
        -C $nestedParent commit --quiet --allow-empty -m "unrelated ancestor root commit"
    $nestedRepo = Join-Path $nestedParent "nested\repo"
    Copy-Item $repo $nestedRepo -Recurse -Force
    Remove-Item (Join-Path $nestedRepo ".git") -Recurse -Force -ErrorAction SilentlyContinue
    $nestedTarget = Join-Path $testRoot "nested target"
    $nestedOutput = & (Join-Path $nestedRepo "install.ps1") -ConfigDir $nestedTarget -Lang en 6>&1
    Assert-Path (Join-Path $nestedTarget "skills\dev\SKILL.md")
    if (-not ($nestedOutput -match "Installed from: no git metadata \(tarball install\)")) {
        throw "Nested no-own-.git install did not report tarball provenance"
    }
    Pass "nested source with no own .git installs via the copy path"

    # A source with its own .git but no git binary on PATH must abort with
    # an actionable error and install nothing — never silently fall back
    # to the copy path, which would ship possibly-dirty working-tree
    # content while looking, from the outside, exactly like the safe case
    # (Issue #44 follow-up).
    $noGitBin = Join-Path $testRoot "fakebin-no-git"
    New-ScratchPathWithout -Destination $noGitBin -ToolNames @("python3", "python", "rtk", "tar")
    $noGitTarget = Join-Path $testRoot "no-git-bin target"
    $originalPath = $env:PATH
    $noGitError = $null
    try {
        $env:PATH = $noGitBin
        & $installer -ConfigDir $noGitTarget -Lang en 2>$null | Out-Null
    }
    catch {
        $noGitError = $_.Exception.Message
    }
    finally {
        $env:PATH = $originalPath
    }
    if (-not $noGitError) { throw "Install unexpectedly succeeded with git unavailable in a git checkout" }
    if ($noGitError -notmatch "git is required to stage it safely from git content") {
        throw "Unexpected error text for git-unavailable abort: $noGitError"
    }
    Assert-Absent $noGitTarget
    Pass "git checkout with git binary unavailable aborts and installs nothing"

    # A genuine git checkout with tar unavailable must abort with an
    # actionable error and install nothing, rather than silently falling
    # back to the working-tree copy while still claiming git provenance
    # (Issue #44 follow-up). Only git/python3/rtk are carried into the
    # scratch PATH; tar is deliberately left out. Unlike the git-missing
    # test above, this one genuinely invokes git during the install (the
    # tar guard is only reached once git-checkout validation succeeds), so
    # it self-checks the shimmed git actually works before asserting
    # anything - a platform where shimming can't preserve a working git
    # (observed on windows-latest when the shim relocated the executable
    # instead of delegating to it) skips with a stated reason rather than
    # asserting the wrong error.
    $noTarBin = Join-Path $testRoot "fakebin-no-tar"
    New-ScratchPathWithout -Destination $noTarBin -ToolNames @("git", "python3", "python", "rtk")
    if (-not (Test-ScratchGitWorks -ScratchPath $noTarBin -RepoPath $repo)) {
        Skip "git checkout with tar unavailable aborts and installs nothing" "could not construct a working git shim on this platform"
    }
    else {
        $noTarTarget = Join-Path $testRoot "no-tar target"
        $originalPath = $env:PATH
        $noTarError = $null
        try {
            $env:PATH = $noTarBin
            & $installer -ConfigDir $noTarTarget -Lang en 2>$null | Out-Null
        }
        catch {
            $noTarError = $_.Exception.Message
        }
        finally {
            $env:PATH = $originalPath
        }
        if (-not $noTarError) { throw "Install unexpectedly succeeded with tar unavailable in a git checkout" }
        $expectedNoTarError = "This is a git checkout of the Skill, but tar is required to stage it safely from git content. Install tar, or install from a release tarball instead."
        if ($noTarError -ne $expectedNoTarError) {
            throw "Unexpected error text for tar-unavailable abort: $noTarError"
        }
        Assert-Absent $noTarTarget
        Pass "git checkout with tar unavailable aborts and installs nothing"
    }

    # The converse of the exclusion case above: an uncommitted *deletion* of
    # a required tracked file must not block installing the perfectly valid
    # committed tree. Preflight has to validate what will actually be
    # installed (the committed content at HEAD), not the mutable working
    # tree (Issue #44 follow-up).
    $dirtyDeletionSource = Join-Path $testRoot "dirty-deletion-source"
    New-Item -ItemType Directory -Force -Path $dirtyDeletionSource | Out-Null
    Copy-Item (Join-Path $repo "*") $dirtyDeletionSource -Recurse -Force
    Remove-Item (Join-Path $dirtyDeletionSource "skills\dev\phases\phase5.md")
    $dirtyDeletionTarget = Join-Path $testRoot "dirty-deletion target"
    & (Join-Path $dirtyDeletionSource "install.ps1") -ConfigDir $dirtyDeletionTarget -Lang en | Out-Null
    Assert-Path (Join-Path $dirtyDeletionTarget "skills\dev\phases\phase5.md")
    Pass "uncommitted deletion of a tracked file does not block installing the committed tree"

    # The other side of that fix: a file *actually* missing from the
    # committed tree (removed and committed, not just deleted on disk) must
    # still be caught by preflight in git mode, before any mutation - the
    # fix above must not have quietly turned preflight validation off for
    # git checkouts.
    $committedBrokenSource = Join-Path $testRoot "committed-broken-source"
    & git clone --quiet -- $repo $committedBrokenSource
    & git -c user.name=test -c user.email=test@example.com `
        -C $committedBrokenSource rm --quiet -- skills/dev/phases/phase5.md
    & git -c user.name=test -c user.email=test@example.com `
        -C $committedBrokenSource commit --quiet -m "remove a required file"
    $committedBrokenTarget = Join-Path $testRoot "committed-broken target"
    $committedBrokenFailed = $false
    try { & (Join-Path $committedBrokenSource "install.ps1") -ConfigDir $committedBrokenTarget -Lang en | Out-Null }
    catch { $committedBrokenFailed = $true }
    if (-not $committedBrokenFailed) { throw "Install with a required file missing from the committed tree unexpectedly succeeded" }
    Assert-Absent $committedBrokenTarget
    Pass "a required file missing from the committed tree is still rejected before mutation"

    # Clean checkout: the install reports the staged commit (Issue #44).
    $cleanTarget = Join-Path $testRoot "clean target"
    $cleanOutput = & $installer -ConfigDir $cleanTarget -Lang en 6>&1
    $expectedCommit = (& git -C $repo rev-parse HEAD).Trim()
    if (-not ($cleanOutput -match "Installed from commit $expectedCommit")) {
        throw "Clean checkout install did not report the staged commit"
    }
    Pass "clean checkout install reports commit provenance"

    # Static guard against the provenance race regressing: the archive call
    # must pin the commit already captured and validated (installCommit),
    # not re-resolve HEAD at staging time, which would reopen a window
    # where a concurrent commit could make the archived content disagree
    # with the commit the install reports (Issue #44 follow-up).
    $installerSource = Get-Content -Raw -LiteralPath $installer
    if ($installerSource -match [regex]::Escape('"archive", "-o", $archiveFile, "HEAD"')) {
        throw "install.ps1 archives HEAD directly instead of the captured installCommit"
    }
    if ($installerSource -notmatch [regex]::Escape('"archive", "-o", $archiveFile, $installCommit')) {
        throw "install.ps1 does not archive the captured installCommit"
    }
    Pass "install.ps1 archives the captured commit, not HEAD, at staging time"

    # An archive failure must name git's own cause: Invoke-GitClean captures
    # the child's stderr and the thrown error carries it (Issue #51, L1).
    # Deleting a loose blob object from a scratch git checkout makes
    # `git archive` fail while rev-parse/ls-tree still validate the checkout,
    # so this reaches the real archive-failure throw rather than a validation
    # abort, and the deleted object's id only ever appears in git's stderr.
    $archiveFailSource = Join-Path $testRoot "archive-fail-source"
    New-Item -ItemType Directory -Force -Path (Join-Path $archiveFailSource "skills\dev") | Out-Null
    Copy-Item -LiteralPath $installer -Destination (Join-Path $archiveFailSource "install.ps1")
    Set-Content -Path (Join-Path $archiveFailSource "skills\dev\SKILL.md") -Value "# payload for the archive-failure case"
    & git init --quiet -- $archiveFailSource
    & git -C $archiveFailSource add -A
    & git -c user.name=test -c user.email=test@example.com `
        -C $archiveFailSource commit --quiet -m "archive-failure fixture commit"
    $missingBlob = (& git -C $archiveFailSource rev-parse "HEAD:skills/dev/SKILL.md").Trim()
    $missingObjectPath = Join-Path (Join-Path (Join-Path $archiveFailSource ".git\objects") $missingBlob.Substring(0, 2)) $missingBlob.Substring(2)
    Remove-Item -LiteralPath $missingObjectPath -Force
    $archiveFailTarget = Join-Path $testRoot "archive-fail target"
    $archiveFailError = $null
    try {
        & (Join-Path $archiveFailSource "install.ps1") -ConfigDir $archiveFailTarget -Lang en 2>$null | Out-Null
    }
    catch {
        $archiveFailError = $_.Exception.Message
    }
    if (-not $archiveFailError) { throw "Install with an unreadable archive object unexpectedly succeeded" }
    if ($archiveFailError -notmatch "git archive failed with exit code") {
        throw "Archive failure did not report git's exit code: $archiveFailError"
    }
    if ($archiveFailError -notmatch [regex]::Escape($missingBlob)) {
        throw "Archive failure did not surface git's stderr (expected the missing object $missingBlob): $archiveFailError"
    }
    Assert-Absent $archiveFailTarget
    Pass "git archive failure surfaces git's stderr in the thrown error"

    # The PowerShell 7 requirement that ProcessStartInfo.ArgumentList implies
    # must be declared up front, so a 5.1 host fails immediately with a
    # version error instead of midway through an install (Issue #51, M1).
    if ($installerSource -notmatch '(?m)^#Requires -Version 7\s*$') {
        throw "install.ps1 does not declare '#Requires -Version 7'"
    }
    Pass "install.ps1 declares its PowerShell 7 requirement"

    # GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR inherited from the caller's
    # environment override git's repository discovery entirely, so without
    # neutralizing them a perfectly valid own-.git checkout could silently
    # validate, archive, and install a completely different repository's
    # committed tree while reporting *its* commit (Issue #44 follow-up).
    # GIT_COMMON_DIR is the linked-worktree analog of GIT_DIR; poisoning it
    # alongside the other two is defense in depth even though it did not
    # independently redirect this worktree-less checkout. Point all three
    # at a disposable repo carrying a planted marker file and confirm the
    # real source's own tree and commit are what actually gets installed.
    $envHijackAlt = Join-Path $testRoot "env-hijack-alt"
    New-Item -ItemType Directory -Force -Path $envHijackAlt | Out-Null
    Copy-Item (Join-Path $repo "skills") $envHijackAlt -Recurse -Force
    & git init --quiet -- $envHijackAlt
    Set-Content -Path (Join-Path $envHijackAlt "skills\dev\ENV_HIJACK_MARKER.txt") -Value "planted by an unrelated repo; must never ship"
    & git -C $envHijackAlt add -A
    & git -c user.name=test -c user.email=test@example.com `
        -C $envHijackAlt commit --quiet -m "alt repo commit carrying a planted marker"
    $envHijackTarget = Join-Path $testRoot "env-hijack target"
    $expectedRealCommit = (& git -C $repo rev-parse HEAD).Trim()
    $originalGitDir = $env:GIT_DIR
    $originalGitWorkTree = $env:GIT_WORK_TREE
    $originalGitCommonDir = $env:GIT_COMMON_DIR
    try {
        $env:GIT_DIR = Join-Path $envHijackAlt ".git"
        $env:GIT_WORK_TREE = $envHijackAlt
        $env:GIT_COMMON_DIR = Join-Path $envHijackAlt ".git"
        $envHijackOutput = & $installer -ConfigDir $envHijackTarget -Lang en 6>&1
    }
    finally {
        if ($null -ne $originalGitDir) { $env:GIT_DIR = $originalGitDir } else { Remove-Item Env:GIT_DIR -ErrorAction SilentlyContinue }
        if ($null -ne $originalGitWorkTree) { $env:GIT_WORK_TREE = $originalGitWorkTree } else { Remove-Item Env:GIT_WORK_TREE -ErrorAction SilentlyContinue }
        if ($null -ne $originalGitCommonDir) { $env:GIT_COMMON_DIR = $originalGitCommonDir } else { Remove-Item Env:GIT_COMMON_DIR -ErrorAction SilentlyContinue }
    }
    Assert-Path (Join-Path $envHijackTarget "skills\dev\SKILL.md")
    Assert-Absent (Join-Path $envHijackTarget "skills\dev\ENV_HIJACK_MARKER.txt")
    if (-not ($envHijackOutput -match "Installed from commit $expectedRealCommit")) {
        throw "Install reported the wrong commit under an inherited GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR"
    }
    Pass "inherited GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR cannot redirect install to another repository"

    # The fix for the hijack above must clean only the CHILD git process's
    # environment, never this process's own: install.ps1 runs via `&` in
    # this same runspace (not as its own process), so an earlier version
    # that removed these variables from $env: for "this process" mutated
    # the CALLER's session too, permanently - proven by this exact probe,
    # which survived even a -DryRun (Issue #44 follow-up). Set sentinel
    # values, run a dry run, and confirm all five are unchanged afterward.
    $sentinelVars = [ordered]@{
        GIT_DIR              = "sentinel-gitdir"
        GIT_WORK_TREE        = "sentinel-worktree"
        GIT_INDEX_FILE       = "sentinel-indexfile"
        GIT_OBJECT_DIRECTORY = "sentinel-objdir"
        GIT_COMMON_DIR       = "sentinel-commondir"
    }
    $originalSentinelValues = @{}
    foreach ($varName in $sentinelVars.Keys) {
        $originalSentinelValues[$varName] = [Environment]::GetEnvironmentVariable($varName, "Process")
        Set-Item "Env:$varName" $sentinelVars[$varName]
    }
    try {
        $sentinelDryTarget = Join-Path $testRoot "sentinel-dry-run"
        & $installer -ConfigDir $sentinelDryTarget -Lang en -DryRun | Out-Null
        foreach ($varName in $sentinelVars.Keys) {
            $currentValue = [Environment]::GetEnvironmentVariable($varName, "Process")
            if ($currentValue -ne $sentinelVars[$varName]) {
                throw "install.ps1 mutated the caller's `$varName during -DryRun (expected '$($sentinelVars[$varName])', got '$currentValue')"
            }
        }
    }
    finally {
        foreach ($varName in $sentinelVars.Keys) {
            if ($null -ne $originalSentinelValues[$varName]) {
                Set-Item "Env:$varName" $originalSentinelValues[$varName]
            }
            else {
                Remove-Item "Env:$varName" -ErrorAction SilentlyContinue
            }
        }
    }
    Pass "sentinel GIT_* env vars survive a -DryRun install unchanged in the caller's session"

    # --- Issue #88: install-time stamping and the Codex discovery link -------

    # Substitution: no literal left, every stamped path resolves, and the
    # detector executes from the installed copy.
    $stampHome = Use-CaseHome "stamp home"
    $stampConfig = Join-Path $testRoot "stamp config"
    & $installer -ConfigDir $stampConfig | Out-Null
    $stampRoot = Get-StampedRoot (Join-Path $stampConfig "skills")
    Assert-Stamped $stampRoot
    $pythonForDetector = Get-Command python3 -ErrorAction SilentlyContinue
    if (-not $pythonForDetector) { $pythonForDetector = Get-Command python }
    # The detector's answer depends on TRAYCER_AGENT_ID / TRAYCER_EPIC_ID, so
    # both outcomes are pinned explicitly: identifiers scrubbed -> exit 2,
    # incomplete; synthetic identifiers -> exit 0, traycer. The caller's own
    # values never count and are restored afterwards.
    # The detector also falls back to <worktree root>/.agent/traycer.env, where
    # the root is the nearest directory above the working directory holding a
    # .git entry: run it from a scratch directory that is its own root (an empty
    # .git marker) so no identity file from the caller's checkout can be found.
    $detectorScript = Join-Path $stampRoot "scripts\detect_execution_backend.py"
    $detectorCwd = Join-Path $testRoot "detector cwd"
    New-Item -ItemType Directory -Force -Path (Join-Path $detectorCwd ".git") | Out-Null
    $savedAgentId = $env:TRAYCER_AGENT_ID
    $savedEpicId = $env:TRAYCER_EPIC_ID
    Push-Location -LiteralPath $detectorCwd
    try {
        Remove-Item Env:TRAYCER_AGENT_ID, Env:TRAYCER_EPIC_ID -ErrorAction SilentlyContinue
        $incompleteText = (& $pythonForDetector.Source $detectorScript | Out-String)
        if ($LASTEXITCODE -ne 2) { throw "Installed detector exited $LASTEXITCODE without session identifiers (expected 2)" }
        $incomplete = $incompleteText | ConvertFrom-Json
        if ($incomplete.detection_status -ne "incomplete" -or $incomplete.execution_backend -ne "incomplete") {
            throw "Installed detector did not report incomplete without session identifiers: $incompleteText"
        }
        $env:TRAYCER_AGENT_ID = "agent-under-test"
        $env:TRAYCER_EPIC_ID = "epic-under-test"
        $readyText = (& $pythonForDetector.Source $detectorScript | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "Installed detector exited $LASTEXITCODE with session identifiers (expected 0)" }
        $ready = $readyText | ConvertFrom-Json
        if ($ready.detection_status -ne "ready" -or $ready.execution_backend -ne "traycer" -or
            $ready.traycer_agent_id -ne "agent-under-test" -or $ready.traycer_epic_id -ne "epic-under-test") {
            throw "Installed detector did not report traycer with session identifiers: $readyText"
        }
    }
    finally {
        Pop-Location
        if ($null -ne $savedAgentId) { $env:TRAYCER_AGENT_ID = $savedAgentId } else { Remove-Item Env:TRAYCER_AGENT_ID -ErrorAction SilentlyContinue }
        if ($null -ne $savedEpicId) { $env:TRAYCER_EPIC_ID = $savedEpicId } else { Remove-Item Env:TRAYCER_EPIC_ID -ErrorAction SilentlyContinue }
    }
    Pass "installed copy has no literal variable, every stamped path resolves, detector answers both ways"

    # The repository keeps the variable form: stamping touches only the installed copy.
    $repoLiterals = Get-ChildItem -LiteralPath (Join-Path $repo "skills\dev") -Recurse -File |
        Select-String -SimpleMatch '${CLAUDE_SKILL_DIR}' -List
    if (-not $repoLiterals) { throw "Repository payload lost its variable form" }
    & $pythonForDetector.Source (Join-Path $repo "scripts\validate_skill.py") --skill-dir (Join-Path $repo "skills\dev") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Repository payload no longer validates" }
    Pass "repository payload keeps the variable form and still validates"

    # Byte-exact stamp for a path with a space, &, $, quotes and %. NTFS cannot
    # name a directory with '|' or a backslash inside a component, so those two
    # are added only on hosts that can (a backslash is a separator on Windows).
    $weirdName = 'we ird & dollar$x ''q'' 100% ;x'
    if (-not $onWindowsHost) { $weirdName += ' pipe | back\slash \1' }
    $weirdHome = Use-CaseHome "weird home"
    $weirdConfig = Join-Path $testRoot $weirdName
    & $installer -ConfigDir $weirdConfig | Out-Null
    $weirdRoot = Get-StampedRoot (Join-Path $weirdConfig "skills")
    Assert-Stamped $weirdRoot
    $weirdSkill = [IO.File]::ReadAllText((Join-Path $weirdRoot "SKILL.md"))
    if (-not $weirdSkill.Contains($weirdRoot + "/scripts/detect_execution_backend.py")) { throw "Special-character path was not stamped byte-exact" }
    if ((Get-LinkTarget (Join-Path $weirdHome ".agents\skills\dev")) -ne $weirdRoot) { throw "Link target is not the byte-exact special-character path" }
    Pass "path with space, &, `$, quotes, % is stamped and linked byte-exact"

    # A relative -Target is stamped as an absolute path.
    $relBase = Join-Path $testRoot "relative target base"
    New-Item -ItemType Directory -Force -Path $relBase | Out-Null
    Push-Location $relBase
    try { & $installer -ConfigDir (Join-Path $testRoot "rel config") -Target "rel\dev" | Out-Null }
    finally { Pop-Location }
    Assert-Stamped (Get-StampedRoot (Join-Path $relBase "rel"))
    Pass "relative -Target is stamped as an absolute path"

    # A target path that itself contains the variable text cannot be stamped
    # faithfully: abort before mutation rather than leave a literal behind.
    $tokenConfig = Join-Path $testRoot 'tok ${CLAUDE_SKILL_DIR} cfg'
    $tokenRejected = $false
    try { & $installer -ConfigDir $tokenConfig | Out-Null } catch { $tokenRejected = $true }
    if (-not $tokenRejected) { throw "Install into a path containing the variable text unexpectedly succeeded" }
    Assert-Absent (Join-Path $tokenConfig "skills\dev")
    if (Get-ChildItem -LiteralPath $tokenConfig -Recurse -Force -Filter ".dev-stage-*" -ErrorAction SilentlyContinue) {
        throw "Stage directory left behind after stamp abort"
    }
    Pass "target path containing the variable text is rejected without residue"

    # Idempotence: a rerun over an existing install yields the identical tree,
    # keeps backing up the previous version, and leaves the link alone.
    $idemHome = Use-CaseHome "idem home"
    $idemConfig = Join-Path $testRoot "idem config"
    & $installer -ConfigDir $idemConfig | Out-Null
    $firstCopy = Join-Path $testRoot "idem-first"
    Copy-Item -LiteralPath (Join-Path $idemConfig "skills\dev") $firstCopy -Recurse
    $idemOutput = Invoke-InstallerText @{ ConfigDir = $idemConfig }
    $firstFiles = Get-ChildItem -LiteralPath $firstCopy -Recurse -File -Force
    foreach ($firstFile in $firstFiles) {
        $relative = $firstFile.FullName.Substring($firstCopy.Length)
        $rerunFile = Join-Path (Join-Path $idemConfig "skills\dev") $relative
        if ((Get-FileHash -LiteralPath $firstFile.FullName).Hash -ne (Get-FileHash -LiteralPath $rerunFile).Hash) {
            throw "Rerun produced a different $relative than the first install"
        }
    }
    $rerunCount = @(Get-ChildItem -LiteralPath (Join-Path $idemConfig "skills\dev") -Recurse -File -Force).Count
    if ($rerunCount -ne $firstFiles.Count) { throw "Rerun produced a different file count than the first install" }
    if (-not (Get-ChildItem -LiteralPath (Join-Path $idemConfig "backups\dev") -Filter SKILL.md -File -Recurse)) { throw "Rerun did not back up the previous install" }
    if ($idemOutput -notmatch "Codex discovery link: up to date") { throw "Rerun did not report the link as up to date" }
    Pass "rerun is idempotent, still backs up, and keeps the link"

    # Link: created on a default install, pointing at the installed Skill.
    $linkHome = Use-CaseHome "link home"
    $linkConfig = Join-Path $testRoot "link config"
    $linkOutput = Invoke-InstallerText @{ ConfigDir = $linkConfig }
    $linkRoot = Get-StampedRoot (Join-Path $linkConfig "skills")
    $linkPath = Join-Path $linkHome ".agents\skills\dev"
    if ((Get-LinkTarget $linkPath) -ne $linkRoot) { throw "Discovery link is missing or does not point at the installed Skill" }
    Assert-Path (Join-Path $linkPath "SKILL.md")
    if ($linkOutput -notmatch "Codex discovery link: created") { throw "Link creation was not reported" }
    Pass "default install creates the discovery link to the installed Skill"

    # Link: a real directory at the path is reported and left untouched.
    $dirHome = Use-CaseHome "dir home"
    $dirLinkPath = Join-Path $dirHome ".agents\skills\dev"
    New-Item -ItemType Directory -Force -Path $dirLinkPath | Out-Null
    Set-Content -Path (Join-Path $dirLinkPath "sentinel.txt") -Value "keep"
    $dirOutput = Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "dir config") }
    if (Get-LinkTarget $dirLinkPath) { throw "A real directory was replaced by a link" }
    Assert-Path (Join-Path $dirLinkPath "sentinel.txt")
    if ($dirOutput -notmatch "already exists and is not a link") { throw "Real directory at the link path was not reported" }
    Assert-Path (Join-Path $testRoot "dir config\skills\dev\SKILL.md")
    Pass "a real directory at the link path is reported and left untouched"

    # Link: a regular file at the path is also left untouched.
    $fileHome = Use-CaseHome "file home"
    $fileLinkPath = Join-Path $fileHome ".agents\skills\dev"
    New-Item -ItemType Directory -Force -Path (Split-Path $fileLinkPath -Parent) | Out-Null
    Set-Content -Path $fileLinkPath -Value "keep"
    Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "file config") } | Out-Null
    if ((Get-LinkTarget $fileLinkPath) -or -not (Test-Path -LiteralPath $fileLinkPath -PathType Leaf)) { throw "A file at the link path was replaced" }
    Pass "a file at the link path is left untouched"

    # Link: a link to a different, existing directory is reported and left.
    $foreignHome = Use-CaseHome "foreign home"
    $foreignDir = Join-Path $testRoot "foreign skill"
    New-Item -ItemType Directory -Force -Path $foreignDir | Out-Null
    $foreignLinkPath = Join-Path $foreignHome ".agents\skills\dev"
    New-TestLink $foreignLinkPath $foreignDir
    $foreignOutput = Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "foreign config") }
    if ((Get-LinkTarget $foreignLinkPath) -ne $foreignDir) { throw "A link to another existing directory was overwritten" }
    if ($foreignOutput -notmatch "Codex discovery link not changed") { throw "Foreign link was not reported" }
    Pass "a link to another existing directory is reported and left untouched"

    # Link: a dangling link holds no data and is replaced, with a report.
    $danglingHome = Use-CaseHome "dangling home"
    $danglingGone = Join-Path $testRoot "deleted scratch install"
    New-Item -ItemType Directory -Force -Path $danglingGone | Out-Null
    $danglingLinkPath = Join-Path $danglingHome ".agents\skills\dev"
    New-TestLink $danglingLinkPath $danglingGone
    Remove-Item -LiteralPath $danglingGone -Force
    $danglingConfig = Join-Path $testRoot "dangling link config"
    $danglingOutput = Invoke-InstallerText @{ ConfigDir = $danglingConfig }
    if ((Get-LinkTarget $danglingLinkPath) -ne (Get-StampedRoot (Join-Path $danglingConfig "skills"))) { throw "Dangling link was not replaced" }
    if ($danglingOutput -notmatch "replaced dangling link \(was -> ") { throw "Dangling link replacement was not reported" }
    Pass "a dangling link is replaced and reported"

    # Link: opt-out creates nothing and leaves an existing link alone.
    $optoutHome = Use-CaseHome "optout home"
    Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "optout config"); NoAgentsLink = $true } | Out-Null
    Assert-Absent (Join-Path $optoutHome ".agents")
    $optoutKeptHome = Use-CaseHome "optout kept home"
    $optoutOther = Join-Path $testRoot "optout other"
    New-Item -ItemType Directory -Force -Path $optoutOther | Out-Null
    $optoutKeptLink = Join-Path $optoutKeptHome ".agents\skills\dev"
    New-TestLink $optoutKeptLink $optoutOther
    Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "optout kept config"); NoAgentsLink = $true } | Out-Null
    if ((Get-LinkTarget $optoutKeptLink) -ne $optoutOther) { throw "-NoAgentsLink touched an existing link" }
    Pass "-NoAgentsLink creates and touches nothing"

    # Link: an explicit -Target is an isolated install; a dry run never links.
    $isoHome = Use-CaseHome "iso home"
    Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "iso config"); Target = (Join-Path $testRoot "iso target\dev") } | Out-Null
    Assert-Absent (Join-Path $isoHome ".agents")
    Assert-Stamped (Get-StampedRoot (Join-Path $testRoot "iso target"))
    Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "iso dry config"); DryRun = $true } | Out-Null
    Assert-Absent (Join-Path $isoHome ".agents")
    Pass "explicit -Target and -DryRun do not create the link"

    # A link that cannot be created (parent path is a file) is reported and
    # never fails the install.
    $blockedHome = Use-CaseHome "blocked home"
    Set-Content -Path (Join-Path $blockedHome ".agents") -Value "not a directory"
    $blockedOutput = Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "blocked config") }
    Assert-Path (Join-Path $testRoot "blocked config\skills\dev\SKILL.md")
    if ($blockedOutput -notmatch "Codex discovery link skipped") { throw "An uncreatable link was not reported as skipped" }
    Pass "an uncreatable link is reported as skipped and the install succeeds"

    # Failure after stamping leaves the previous install untouched and no residue.
    $stampFailHome = Use-CaseHome "stampfail home"
    $stampFailConfig = Join-Path $testRoot "stampfail config"
    New-Item -ItemType Directory -Force -Path (Join-Path $stampFailConfig "skills\dev") | Out-Null
    Set-Content -Path (Join-Path $stampFailConfig "skills\dev\old.txt") -Value "old skill"
    $env:DEV_INSTALL_FAIL_AT = "after-stamp"
    $stampFailed = $false
    try { & $installer -ConfigDir $stampFailConfig | Out-Null } catch { $stampFailed = $true }
    Remove-Item Env:DEV_INSTALL_FAIL_AT -ErrorAction SilentlyContinue
    if (-not $stampFailed) { throw "Injected after-stamp failure unexpectedly succeeded" }
    Assert-Path (Join-Path $stampFailConfig "skills\dev\old.txt")
    if (Get-ChildItem -LiteralPath $stampFailConfig -Recurse -Force -Filter ".dev-stage-*" -ErrorAction SilentlyContinue) {
        throw "Stage directory left behind after after-stamp failure"
    }
    Assert-Absent (Join-Path $stampFailHome ".agents")
    Assert-Absent (Join-Path $stampFailConfig "backups")
    Pass "failure after stamping keeps the previous install and leaves no residue"

    # A path with a newline or carriage return cannot be stamped faithfully:
    # refuse it before any change instead of exiting 0 with references to a
    # path that does not exist. Strings alone reach the refusal, so this runs
    # on Windows too; only the working-directory case needs a real directory.
    function Assert-Refused([string]$Label, [hashtable]$InstallerArguments, [string[]]$MustStayAbsent) {
        $refusal = $null
        try { & $installer @InstallerArguments | Out-Null } catch { $refusal = $_.Exception.Message }
        if (-not $refusal) { throw "$Label unexpectedly succeeded" }
        if ($refusal -notmatch "must not contain a newline or carriage return") { throw "$Label was refused for the wrong reason: $refusal" }
        foreach ($absentPath in $MustStayAbsent) { Assert-Absent $absentPath }
    }
    $nlHome = Use-CaseHome "nl home"
    foreach ($nlConfig in @(
        ((Join-Path $testRoot "nl") + "`n" + "config"),
        ((Join-Path $testRoot "nl trailing") + "`n"),
        ((Join-Path $testRoot "nl cr") + "`r" + "config"))) {
        Assert-Refused "Install into a path with a line break" @{ ConfigDir = $nlConfig } @($nlConfig)
    }
    Assert-Refused "-Target with a line break" @{ ConfigDir = (Join-Path $testRoot "nl target config"); Target = ((Join-Path $testRoot "nl target") + "`n" + "x\dev") } @((Join-Path $testRoot "nl target config"))
    if (-not $onWindowsHost) {
        $nlRelativeBase = (Join-Path $testRoot "nl relative") + "`n" + "base"
        New-Item -ItemType Directory -Force -Path $nlRelativeBase | Out-Null
        Push-Location -LiteralPath $nlRelativeBase
        try { Assert-Refused "Relative -Target under a working directory with a line break" @{ ConfigDir = (Join-Path $testRoot "nl relative config"); Target = "rel\dev" } @((Join-Path $testRoot "nl relative config")) }
        finally { Pop-Location }
        Assert-Absent (Join-Path $nlRelativeBase "rel")
    }
    $env:USERPROFILE = (Join-Path $testRoot "nl link") + "`n" + "home"
    Assert-Refused "Install with a line break in the link path" @{ ConfigDir = (Join-Path $testRoot "nl link config") } @((Join-Path $testRoot "nl link config"))
    Invoke-InstallerText @{ ConfigDir = (Join-Path $testRoot "nl link opt-out config"); NoAgentsLink = $true } | Out-Null
    Assert-Path (Join-Path $testRoot "nl link opt-out config\skills\dev\SKILL.md")
    Pass "a path containing a newline or carriage return is refused before any change"

    # Help documents the flag.
    $helpText = Get-Help $installer -Full | Out-String
    if ($helpText -notmatch "NoAgentsLink") { throw "Get-Help does not document -NoAgentsLink" }
    Pass "help documents -NoAgentsLink"

    # The help must name exactly the paths the line-break guard checks (config
    # dir, install target, the Codex link path whenever link creation is enabled
    # -- a default install, dry runs included, not with -NoAgentsLink or an
    # explicit -Target -- and the working directory for a relative target) and
    # must not claim the home directory is checked on its own.
    $helpFlat = ($helpText -replace '\s+', ' ')
    foreach ($guarded in @("config dir", "install target", "Codex discovery link path", "checked whenever link creation is enabled", "dry runs included", "not with -NoAgentsLink or an explicit -Target", "relative -Target also checks the working directory", "home directory is not checked on its own")) {
        if (-not $helpFlat.Contains($guarded)) { throw "Get-Help line-break wording does not mention: $guarded" }
    }
    if ($helpFlat.Contains("(config dir, target, home)")) { throw "Get-Help still claims home is refused" }
    if ($helpFlat.Contains("only when a link is made")) { throw "Get-Help still limits the link-path check to when a link is made" }
    Pass "help names exactly the paths the line-break guard checks"

    Write-Host "All $passCount PowerShell installer tests passed."
}
finally {
    Remove-Item Env:DEV_INSTALL_FAIL_AT -ErrorAction SilentlyContinue
    if ($null -ne $originalUserProfile) { $env:USERPROFILE = $originalUserProfile } else { Remove-Item Env:USERPROFILE -ErrorAction SilentlyContinue }
    if (Test-Path $testRoot) { Remove-Item $testRoot -Recurse -Force }
}
