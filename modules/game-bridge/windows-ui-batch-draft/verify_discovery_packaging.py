"""Source-only isolation checks; not a C#/PowerShell execution or runtime safety proof."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMPILES = {
    'DiscoveryCandidateEntrypoint.cs', 'DiscoveryCandidateHost.cs',
    'DiscoveryCandidateConfiguration.cs', 'DiscoveryPolicy.cs', 'DiscoveryCollector.cs',
    'BatchNativeBackend.cs', 'WindowsLoadedModuleLease.Discovery.cs',
    '../windows-ui-smoke-draft/WindowsSmokeReader.cs',
    '../windows-smoke-draft/WindowsSmokePolicy.cs',
    '../windows-smoke-draft/WindowsLoadedModuleLease.cs',
    '../windows-smoke-draft/MetadataSmoke.cs', '../src/MainThreadGuard.cs',
    '../src/WindowsProbeScheduler.cs', '../src/WindowsProbeConfiguration.cs',
}
ARTIFACT = 'bridge-windows-x64-DISCOVERY-OPT-IN-NO-CONFIG'
PATHS = [
    'build/windows-discovery/FootballAssistant.WindowsDiscoveryCandidate.dll',
    'build/windows-discovery/FootballAssistant.WindowsDiscoveryCandidate.deps.json',
    'modules/game-bridge/windows-ui-batch-draft/Prepare-DiscoveryCandidate.ps1',
    'modules/game-bridge/windows-ui-batch-draft/Request-Discovery.ps1',
    'modules/game-bridge/windows-ui-batch-draft/DISCOVERY.md', 'LICENSE',
]


def project_check(source):
    project = ET.fromstring(source)
    assert project.findtext('.//AssemblyName') == 'FootballAssistant.WindowsDiscoveryCandidate'
    assert project.findtext('.//EnableDefaultCompileItems') == 'false'
    assert project.findtext('.//TargetFramework') == 'net10.0'
    assert project.findtext('.//AllowUnsafeBlocks') == 'true'
    assert not project.findall('Import') and not project.findall('Target')
    items = [item for group in project.findall('ItemGroup') for item in group]
    assert all(item.tag == 'Compile' for item in items), 'No content/configuration copying or project/package references'
    actual = [item.attrib['Include'] for item in items]
    assert len(actual) == len(COMPILES) and set(actual) == COMPILES, 'Exact discovery-only compilation list'
    assert all(set(item.attrib) <= {'Include', 'Link'} and not list(item) for item in items)


def artifact_check(source):
    assert source.count('name: ' + ARTIFACT) == 1
    block = source.split('name: ' + ARTIFACT, 1)[1]
    paths = block.split('path: |', 1)[1].split('if-no-files-found:', 1)[0]
    assert [line.strip() for line in paths.splitlines() if line.strip()] == PATHS, 'Explicit artifact allowlist only; no configuration/request/private data'
    assert 'dotnet build modules/game-bridge/windows-ui-batch-draft/FootballAssistant.WindowsDiscoveryCandidate.csproj --configuration Release --output build/windows-discovery' in source
    # Prepare/Request helpers may be packaged, never run by the no-game build.
    assert not re.search(r'run:.*(?:Prepare-DiscoveryCandidate|Request-Discovery)\.ps1', source)


def must_reject(check, source):
    try:
        check(source)
    except AssertionError:
        return
    raise AssertionError('Isolation mutation was not rejected')


def main():
    project = (HERE / 'FootballAssistant.WindowsDiscoveryCandidate.csproj').read_text()
    workflow = (ROOT / '.github/workflows/windows-bridge-probe.yml').read_text()
    project_check(project)
    artifact_check(workflow)
    for source in COMPILES:
        assert (HERE / source).is_file(), source
    host = (HERE / 'DiscoveryCandidateHost.cs').read_text()
    lease = (HERE / 'WindowsLoadedModuleLease.Discovery.cs').read_text()
    collector = (HERE / 'DiscoveryCollector.cs').read_text()
    assert host.index('DiscoveryCandidateConfiguration.Read(assemblyPath)') < host.index('platform.Start(Tick')
    assert host.index('if (ready is null || pending is null) return;') < host.index('ready.RunDiscoveryOnce')
    assert 'RunMetadata(' not in host and 'RunUiResolveOnce(' not in host and 'RunBatchChunk(' not in host
    assert 'ReadWindowsScanIdentity(policy.Approval.Context.EntryThread)' in lease
    assert collector.index('Stopwatch.GetTimestamp()') < collector.index('policy.TryBegin(')
    prepare = (HERE / 'Prepare-DiscoveryCandidate.ps1').read_text()
    assert "schema_version = 3; mode = 'ui_discovery_once'" in prepare
    assert "'footballassistant.windows-discovery.json'" in prepare
    assert "'FootballAssistant.WindowsDiscoveryCandidate.dll'" in prepare
    assert 'Get-Process -Name fm' in prepare and 'ReparsePoint' in prepare
    assert 'GetFileInformationByHandle' in prepare and '$index -eq 0' in prepare
    assert 'Start-Process' not in prepare and 'RequestName' not in prepare
    assert not (HERE / 'footballassistant.windows-discovery.json').exists()
    assert not (HERE / 'discovery-request.json').exists()
    must_reject(project_check, project.replace('<EnableDefaultCompileItems>false', '<EnableDefaultCompileItems>true'))
    must_reject(project_check, project.replace('<Compile Include="DiscoveryPolicy.cs"', '<Compile Include="BatchPolicy.cs"'))
    must_reject(project_check, project.replace('</ItemGroup>', '<Content Include="*.json" /></ItemGroup>'))
    for forbidden in ['build/windows-discovery/**', 'modules/game-bridge/windows-ui-batch-draft/footballassistant.windows-discovery.json', 'modules/game-bridge/windows-ui-batch-draft/discovery-request.json']:
        must_reject(artifact_check, workflow.replace(PATHS[0], forbidden))
    print('Discovery packaging static checks passed (6 isolation mutations rejected; no runtime/configuration enabled).')


if __name__ == '__main__':
    main()
