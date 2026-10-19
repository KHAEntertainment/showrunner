<#
.SYNOPSIS
Installs the English /dev personal Skill for Claude Code on Windows.

.DESCRIPTION
Installs skills\dev as a personal Claude Code Skill. The installed copy has its
${CLAUDE_SKILL_DIR} references replaced by its absolute path, so harnesses other
than Claude Code can resolve them.

A default install also links "$env:USERPROFILE\.agents\skills\dev" to the
installed Skill (a junction on Windows, a symbolic link elsewhere) so Codex and
other harnesses discover the same copy. An existing real directory, file, or
link to another existing directory at that path is reported and left untouched;
a link whose target no longer exists is replaced. That guarantee assumes nothing
else writes to that path during the install. If the link cannot be created the
install still succeeds and the skip is reported.

A newline or carriage return in the config dir, the install target, or the Codex
discovery link path is refused before anything is changed. The link path is
checked whenever link creation is enabled: a default install, dry runs included,
but not with -NoAgentsLink or an explicit -Target. A relative -Target also checks
the working directory. The home directory is not checked on its own.

A custom -Target installs in isolation: it does not migrate legacy commands by
default and does not create the Codex discovery link.

.PARAMETER Lang
Only "en" is accepted; Chinese is not distributed.

.PARAMETER ConfigDir
Claude Code configuration directory. Defaults to CLAUDE_CONFIG_DIR or "$env:USERPROFILE\.claude".

.PARAMETER Target
Exact dev Skill directory to install into; must end in \dev.

.PARAMETER MigrateLegacy
Back up and remove legacy commands\dev.md and commands\dev.

.PARAMETER KeepLegacy
Leave legacy commands in place.

.PARAMETER NoAgentsLink
Do not create or touch the "$env:USERPROFILE\.agents\skills\dev" Codex discovery link.

.PARAMETER DryRun
Validate and report without changing any files.
#>
#Requires -Version 7
# Windows PowerShell 5.1 cannot run this installer (Invoke-GitClean uses
# ProcessStartInfo.ArgumentList, a PowerShell 7 / modern .NET API). Declaring
# the requirement here fails a 5.1 host immediately with this version error
# instead of partway through an install (Issue #51).
[CmdletBinding()]
param(
    [string]$Lang = "en",
    [string]$ConfigDir = $(if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE ".claude" }),
    [string]$Target,
    [switch]$MigrateLegacy,
    [switch]$KeepLegacy,
    [switch]$NoAgentsLink,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($Lang -ne "en") {
    throw "This maintained distribution is English-only; use -Lang en."
}
if ($MigrateLegacy -and $KeepLegacy) {
    throw "Choose either -MigrateLegacy or -KeepLegacy, not both."
}

$source = Join-Path $PSScriptRoot "skills\dev"
$validator = Join-Path $PSScriptRoot "scripts\validate_skill.py"

# When PSScriptRoot is itself the root of a git checkout that tracks
# skills/dev, stage from committed content instead of the working tree so
# untracked/ignored files and uncommitted edits never ship. A release
# tarball (or the Homebrew libexec copy, ADR-007) has no .git, so it falls
# back to the working-tree copy unchanged. This is decided by a filesystem
# check, not by whether the git command happens to be usable: whether
# PSScriptRoot *looks like* a git checkout (a .git entry — directory or,
# for a linked worktree, the "gitdir: ..." file — is present) and whether
# it can actually be *validated* as one are kept separate on purpose. A
# directory that looks like a checkout but can't be validated (git is
# missing, or validation fails for any other reason) must never silently
# fall back to the copy path — that would ship possibly-dirty working-tree
# content while looking, from the outside, exactly like the safe case.
# Resulting matrix:
#   own .git + validates + tar available  -> git-archive path
#   own .git + validates + tar missing    -> abort (checked further down,
#                                             once tar's availability is known)
#   own .git + does not validate          -> abort (git missing, or the
#                                             directory isn't actually a
#                                             valid checkout tracking
#                                             skills/dev at HEAD)
#   no own .git                           -> copy path, tarball provenance
#                                             (git/tar not required here)
$hasOwnGit = Test-Path (Join-Path $PSScriptRoot ".git")
$gitCommand = Get-Command git -ErrorAction SilentlyContinue
$tarCommand = Get-Command tar -ErrorAction SilentlyContinue
$isGitCheckout = $false
$gitValidationError = $null
$installCommit = ""

# GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY, and
# GIT_COMMON_DIR, if inherited from the caller's environment, override
# `-C`'s repository discovery entirely — every git call below goes
# through this helper rather than a bare `& $gitCommand.Source ...` so an
# inherited GIT_DIR pointed at some other repository can't make the
# installer validate, archive, and install that other repository's
# committed skills/dev tree while still reporting *its* commit, even
# though the own-.git check above passed on PSScriptRoot. GIT_COMMON_DIR
# (the linked-worktree analog of GIT_DIR) is included for the same
# reason, as defense in depth alongside the other four, even though it
# did not independently redirect a worktree-less checkout in testing.
# This builds the CHILD process's environment block directly instead of
# removing the variables from $env: for this process: $env: is
# process-wide, not scoped to a script or function, so a blanket
# `Remove-Item Env:GIT_DIR` here would corrupt the CALLER's session too
# whenever this script runs via `&` in the same runspace (as this repo's
# own test harness does) rather than as its own process — proven by a
# sentinel-variable probe that survived a -DryRun run. Only git ever sees
# the cleaned environment; this process's own $env: table is never
# touched.
function Invoke-GitClean {
    param(
        [Parameter(Mandatory)][string[]]$ArgumentList
    )
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new($gitCommand.Source)
    foreach ($argItem in $ArgumentList) { $startInfo.ArgumentList.Add($argItem) }
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    # Accessing EnvironmentVariables populates it from this process's own
    # environment; removing keys here only affects the dictionary handed
    # to the child process about to be started.
    foreach ($riskyGitVar in @("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR")) {
        if ($startInfo.EnvironmentVariables.ContainsKey($riskyGitVar)) {
            $startInfo.EnvironmentVariables.Remove($riskyGitVar)
        }
    }
    $proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $startInfo
    $proc.Start() | Out-Null
    # Every call site here produces at most a few lines of text (or none,
    # when output goes to a file via -o), so reading stdout then stderr
    # sequentially - rather than asynchronously - cannot deadlock in
    # practice: neither stream ever approaches the OS pipe buffer size.
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    [PSCustomObject]@{
        StdOut   = $stdout
        StdErr   = $stderr
        ExitCode = $proc.ExitCode
    }
}

if ($hasOwnGit) {
    if (-not $gitCommand) {
        $gitValidationError = "This looks like a git checkout of the Skill (a .git entry is present at $PSScriptRoot), but git is required to stage it safely from git content. Install git, or install from a release tarball instead."
    }
    else {
        # An empty --show-prefix means PSScriptRoot IS the repo root (git
        # answers this itself, so it needs no path comparison and sidesteps
        # symlink resolution mismatches between PowerShell's Resolve-Path
        # and git's internal realpath handling, e.g. macOS's
        # /var -> /private/var). installCommit is captured here, once, as
        # part of the same validation chain, and reused verbatim for every
        # later archive: resolving HEAD again at staging time would leave a
        # window where a concurrent commit on this checkout could make the
        # archived content disagree with the commit the install reports.
        $prefixResult = Invoke-GitClean -ArgumentList @("-C", $PSScriptRoot, "rev-parse", "--show-prefix")
        $gitPrefix = $prefixResult.StdOut.Trim()
        $prefixOk = ($prefixResult.ExitCode -eq 0 -and [string]::IsNullOrEmpty($gitPrefix))
        $trackedSkillsDev = $null
        if ($prefixOk) {
            $trackedResult = Invoke-GitClean -ArgumentList @("-C", $PSScriptRoot, "ls-tree", "-d", "HEAD", "--", "skills/dev")
            $trackedSkillsDev = $trackedResult.StdOut.Trim()
        }
        if ($prefixOk -and $trackedResult.ExitCode -eq 0 -and $trackedSkillsDev) {
            $commitResult = Invoke-GitClean -ArgumentList @("-C", $PSScriptRoot, "rev-parse", "HEAD")
            $installCommit = $commitResult.StdOut.Trim()
            if ($commitResult.ExitCode -eq 0 -and $installCommit) {
                $isGitCheckout = $true
            }
        }
        if (-not $isGitCheckout) {
            $installCommit = ""
            $gitValidationError = "This looks like a git checkout of the Skill (a .git entry is present at $PSScriptRoot), but its git metadata could not be validated (it may not be the repository root, or skills/dev may not be tracked at HEAD). Refusing to guess; install from a clean checkout or a release tarball instead."
        }
    }
}

# Archives $installCommit's skills/dev into $Destination (which must
# already exist and be empty). Shared by the preflight check below and the
# real staging step further down so both extract the exact same commit
# through the exact same path.
function Export-CommittedSkillsDev([string]$Destination) {
    $archiveFile = Join-Path ([IO.Path]::GetTempPath()) ("dev-archive-" + [guid]::NewGuid() + ".tar")
    try {
        # Written to a temp file rather than piping git's binary stdout
        # through the PowerShell pipeline: native-to-native pipes in
        # PowerShell can reinterpret/corrupt binary streams (encoding and
        # newline translation), which a file handoff avoids entirely.
        $archiveResult = Invoke-GitClean -ArgumentList @("-C", $PSScriptRoot, "archive", "-o", $archiveFile, $installCommit, "--", "skills/dev")
        if ($archiveResult.ExitCode -ne 0) {
            # Name git's own cause (Issue #51, L1): its stderr is the only
            # thing that says why the archive failed.
            $gitStderr = $archiveResult.StdErr.Trim()
            $archiveDetail = if ($gitStderr) { ": $gitStderr" } else { "" }
            throw "git archive failed with exit code $($archiveResult.ExitCode)$archiveDetail"
        }
        # Extract from inside the destination instead of `tar -C`: GNU tar
        # processes backslash escapes in a -C argument, and $Destination can
        # live under a caller-chosen path (TMPDIR, or the target's parent).
        Push-Location -LiteralPath $Destination
        try { & $tarCommand.Source -xf $archiveFile --strip-components=2 }
        finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw "tar extraction failed with exit code $LASTEXITCODE" }
    }
    finally {
        Remove-Item $archiveFile -ErrorAction SilentlyContinue
    }
}

$targetWasExplicit = $PSBoundParameters.ContainsKey("Target")
if (-not $Target) {
    $Target = Join-Path $ConfigDir "skills\dev"
}
# Codex discovery link decision. Home is the same one the unsafe-target check
# below uses (USERPROFILE, with $HOME as the non-Windows fallback so the suite
# can run under pwsh on macOS/Linux); tests override it by setting USERPROFILE.
$agentsLinkPath = $null
$agentsLinkSkip = $null
if ($NoAgentsLink) {
    $agentsLinkSkip = "-NoAgentsLink"
}
elseif ($targetWasExplicit) {
    $agentsLinkSkip = "explicit -Target installs in isolation"
}
else {
    $agentsHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
    $agentsLinkPath = Join-Path $agentsHome ".agents\skills\dev"
}
# The stamp is written into text files, where a line break in a path corrupts
# it, so refuse such a path up front rather than stamp a wrong one. The working
# directory only matters when a relative path is resolved against it.
function Assert-NoLineBreak([string]$Name, [string]$Value) {
    if ($Value -match '[\r\n]') {
        throw "$Name must not contain a newline or carriage return: $($Value -replace '\r', '\r' -replace '\n', '\n')"
    }
}
Assert-NoLineBreak "Config dir" $ConfigDir
Assert-NoLineBreak "Install target" $Target
Assert-NoLineBreak "Codex discovery link path" $agentsLinkPath
if (-not [IO.Path]::IsPathRooted($Target)) { Assert-NoLineBreak "Working directory" (Get-Location).ProviderPath }
if ((Split-Path $Target -Leaf) -ne "dev") {
    throw "-Target must be the exact dev Skill directory and end in \dev: $Target"
}
$unsafeTargets = @([IO.Path]::GetPathRoot($Target), $env:USERPROFILE, $ConfigDir)
if ($unsafeTargets -contains $Target) {
    throw "Unsafe install target: $Target"
}
if (Test-Path $Target) {
    $targetItem = Get-Item $Target -Force
    if ($targetItem.LinkType) { throw "Refusing to replace symlink target: $Target" }
}

$pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue }
if (-not $pythonCommand) { throw "Python 3 is required for validation." }
$pythonExe = $pythonCommand.Source
if (-not (Get-Command rtk -ErrorAction SilentlyContinue)) { throw "RTK is required by this customized /dev workflow." }
if ($gitValidationError) {
    throw $gitValidationError
}
if ($isGitCheckout -and -not $tarCommand) {
    throw "This is a git checkout of the Skill, but tar is required to stage it safely from git content. Install tar, or install from a release tarball instead."
}
# Preflight validates the tree that will actually be installed. In git
# mode that is the committed content at installCommit, not $source: an
# uncommitted local edit or deletion under $source must not block
# installing a perfectly valid committed tree, and conversely, a genuinely
# broken committed tree must still be caught here, before any mutation.
# This costs a second archive/extract beyond the one staging does later
# (cheap for a skill-sized tree) rather than skipping preflight validation
# for git mode entirely.
if ($isGitCheckout) {
    $preflightDir = Join-Path ([IO.Path]::GetTempPath()) ("dev-preflight-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $preflightDir | Out-Null
    try {
        Export-CommittedSkillsDev -Destination $preflightDir
        & $pythonExe $validator --skill-dir $preflightDir
        if ($LASTEXITCODE -ne 0) { throw "Skill validation failed." }
    }
    finally {
        Remove-Item $preflightDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
else {
    & $pythonExe $validator --skill-dir $source
    if ($LASTEXITCODE -ne 0) { throw "Skill validation failed." }
}

$migrate = if ($MigrateLegacy) { $true } elseif ($KeepLegacy) { $false } else { -not $targetWasExplicit }
$legacyFile = Join-Path $ConfigDir "commands\dev.md"
$legacyDir = Join-Path $ConfigDir "commands\dev"
if ($migrate) {
    foreach ($legacyPath in @($legacyFile, $legacyDir)) {
        if (Test-Path $legacyPath) {
            $legacyItem = Get-Item $legacyPath -Force
            if ($legacyItem.LinkType) { throw "Refusing to migrate symlink path: $legacyPath" }
        }
    }
}

Write-Host "Source: $source"
Write-Host "Target: $Target"
Write-Host "Legacy migration: $migrate"
if ($agentsLinkPath) { Write-Host "Codex discovery link: $agentsLinkPath" }
else { Write-Host "Codex discovery link: skipped ($agentsLinkSkip)" }
if ($DryRun) {
    Write-Host "DRY RUN: validation passed; no files changed."
    return
}

$targetParent = Split-Path $Target -Parent
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-$PID"
$backup = Join-Path $ConfigDir "backups\dev\$stamp"
$stage = Join-Path $targetParent ".dev-stage-$stamp"
$hadTarget = $false
$hadLegacyFile = $false
$hadLegacyDir = $false
$installedNew = $false

try {
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
    New-Item -ItemType Directory -Path $stage | Out-Null
    if ($isGitCheckout) {
        # Archives the exact commit already captured and validated above,
        # not HEAD again: re-resolving HEAD here would reopen the race the
        # earlier capture exists to close (see installCommit's capture site).
        Export-CommittedSkillsDev -Destination $stage
    }
    else {
        Copy-Item (Join-Path $source "*") $stage -Recurse -Force
    }
    & $pythonExe $validator --skill-dir $stage
    if ($LASTEXITCODE -ne 0) { throw "Staged Skill validation failed." }

    # Stamp only after the staged (git-archived, still variable-form) payload
    # has passed validation, and only on the staged copy that is about to
    # become the installed one: the repository, the preflight tree, and the
    # validator's variable-form pins are never modified. The stamped value is
    # the final absolute install path, not the stage path.
    $targetAbs = Join-Path (Resolve-Path -LiteralPath $targetParent).ProviderPath (Split-Path $Target -Leaf)
    Assert-NoLineBreak "Resolved install target" $targetAbs
    # Byte-exact literal replacement: Latin-1 maps every byte to one char, so
    # the round trip is lossless for any file content, and String.Replace is
    # ordinal (no regex, no $-substitution), so space, &, |, \, $ and quotes in
    # the path cannot corrupt it. The replacement is the path's UTF-8 bytes
    # seen through Latin-1, so non-ASCII paths are written as UTF-8.
    $stampNeedle = '${CLAUDE_SKILL_DIR}'
    $latin1 = [Text.Encoding]::GetEncoding(28591)
    $stampValue = $latin1.GetString([Text.Encoding]::UTF8.GetBytes($targetAbs))
    $stampedCount = 0
    foreach ($stampFile in Get-ChildItem -LiteralPath $stage -Recurse -File -Force) {
        if ($stampFile.LinkType) { continue }
        $stampText = $latin1.GetString([IO.File]::ReadAllBytes($stampFile.FullName))
        if (-not $stampText.Contains($stampNeedle)) { continue }
        $stampText = $stampText.Replace($stampNeedle, $stampValue)
        if ($stampText.Contains($stampNeedle)) {
            throw "Stamping left a literal `${CLAUDE_SKILL_DIR} in $($stampFile.FullName); the install path must not itself contain that text."
        }
        [IO.File]::WriteAllBytes($stampFile.FullName, $latin1.GetBytes($stampText))
        $stampedCount++
    }
    Write-Host "Stamped $stampedCount files with $targetAbs"

    if ($env:DEV_INSTALL_FAIL_AT -eq "after-stamp") { throw "Injected failure after stamp." }

    if ($env:DEV_INSTALL_FAIL_AT -eq "after-stage") { throw "Injected failure after stage." }

    if (Test-Path $Target) {
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        Move-Item $Target (Join-Path $backup "skill")
        $hadTarget = $true
    }

    if ($migrate -and ((Test-Path $legacyFile) -or (Test-Path $legacyDir))) {
        $legacyBackup = Join-Path $backup "legacy"
        New-Item -ItemType Directory -Force -Path $legacyBackup | Out-Null
        if (Test-Path $legacyFile) {
            Move-Item $legacyFile (Join-Path $legacyBackup "dev.md")
            $hadLegacyFile = $true
        }
        if (Test-Path $legacyDir) {
            Move-Item $legacyDir (Join-Path $legacyBackup "dev")
            $hadLegacyDir = $true
        }
    }

    if ($env:DEV_INSTALL_FAIL_AT -eq "after-backup") { throw "Injected failure after backup." }

    Move-Item $stage $Target
    $installedNew = $true
    if ($env:DEV_INSTALL_FAIL_AT -eq "after-install") { throw "Injected failure after install." }
}
catch {
    Write-Warning "Install failed; rolling back: $_"
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    if ($installedNew -and (Test-Path $Target)) { Remove-Item $Target -Recurse -Force }
    if ($hadTarget) { Move-Item (Join-Path $backup "skill") $Target }
    if ($hadLegacyFile) {
        New-Item -ItemType Directory -Force -Path (Split-Path $legacyFile -Parent) | Out-Null
        Move-Item (Join-Path $backup "legacy\dev.md") $legacyFile
    }
    if ($hadLegacyDir) {
        New-Item -ItemType Directory -Force -Path (Split-Path $legacyDir -Parent) | Out-Null
        Move-Item (Join-Path $backup "legacy\dev") $legacyDir
    }
    throw
}

Write-Host "Installed /dev Skill at $Target"
if ($isGitCheckout) {
    Write-Host "Installed from commit $installCommit"
}
else {
    Write-Host "Installed from: no git metadata (tarball install)"
}
if (Test-Path $backup) { Write-Host "Previous files backed up at $backup" }

# Codex discovery link. Runs after the install is committed and outside the
# rollback try/catch: a link problem is reported, never fatal, and never undoes
# or blocks the install. Nothing that holds data is overwritten.
function Set-AgentsSkillLink {
    if (-not $agentsLinkPath) {
        Write-Host "Codex discovery link: skipped ($agentsLinkSkip)"
        return
    }
    $onWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or ($IsWindows -eq $true)
    $linkType = if ($onWindows) { "Junction" } else { "SymbolicLink" }
    try {
        $existing = Get-Item -LiteralPath $agentsLinkPath -Force -ErrorAction SilentlyContinue
        if ($existing -and $existing.LinkType) {
            $oldTarget = [string](@($existing.Target)[0])
            # Test-Path on the link itself reports true for a dangling link on
            # PowerShell 7, so test the target it names (relative to the link).
            $oldTargetPath = if ([IO.Path]::IsPathRooted($oldTarget)) { $oldTarget } else { Join-Path (Split-Path $agentsLinkPath -Parent) $oldTarget }
            if (Test-Path -LiteralPath $oldTargetPath) {
                $comparison = if ($onWindows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
                if ([string]::Equals($oldTarget.TrimEnd("\", "/"), $targetAbs.TrimEnd("\", "/"), $comparison)) {
                    Write-Host "Codex discovery link: up to date: $agentsLinkPath -> $oldTarget"
                }
                else {
                    Write-Warning "Codex discovery link not changed: $agentsLinkPath already points to $oldTarget; leaving it. Remove it to let the installer link $targetAbs."
                }
                return
            }
            # Dangling: holds no data and would otherwise block the link forever.
            # The check-then-delete below is not atomic: it assumes no concurrent
            # writer swaps this entry in between (accepted for a single-user installer).
            $existing.Delete()
            New-Item -ItemType $linkType -Path $agentsLinkPath -Value $targetAbs | Out-Null
            Write-Host "Codex discovery link: replaced dangling link (was -> $oldTarget): $agentsLinkPath -> $targetAbs"
            return
        }
        if ($existing) {
            Write-Warning "Codex discovery link not created: $agentsLinkPath already exists and is not a link; leaving it."
            return
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $agentsLinkPath -Parent) | Out-Null
        New-Item -ItemType $linkType -Path $agentsLinkPath -Value $targetAbs | Out-Null
        Write-Host "Codex discovery link: created $agentsLinkPath -> $targetAbs"
    }
    catch {
        Write-Warning "Codex discovery link skipped: $_"
    }
}
Set-AgentsSkillLink
Write-Host "Restart Claude Code, then invoke /dev."
