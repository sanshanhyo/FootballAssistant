"""Source/build isolation only, not native execution or runtime safety evidence."""
from pathlib import Path
import xml.etree.ElementTree as ET
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMPILES = {
    'FiniteRowsCandidateEntrypoint.cs','FiniteRowsCandidateHost.cs','FiniteRowsCandidateConfiguration.cs','FiniteRowsPolicy.cs',
    'GroupedDiscoveryValidation.cs','DiscoveryCandidateConfiguration.cs','DiscoveryPolicy.cs','DiscoveryCollector.cs',
    'TargetedDiscoveryCollector.cs','AttributeRowSelection.cs','FiniteCaptureSelection.cs','PageDiscoveryValidation.cs','BatchNativeBackend.cs','WindowsLoadedModuleLease.Discovery.cs',
    '../windows-ui-smoke-draft/WindowsSmokeReader.cs','../windows-smoke-draft/WindowsSmokePolicy.cs',
    '../windows-smoke-draft/WindowsLoadedModuleLease.cs','../windows-smoke-draft/MetadataSmoke.cs',
    '../src/MainThreadGuard.cs','../src/WindowsProbeScheduler.cs','../src/WindowsProbeConfiguration.cs',
}
PATHS = [
    'build/windows-finite-rows/FootballAssistant.WindowsFiniteRowsCandidate.dll',
    'build/windows-finite-rows/FootballAssistant.WindowsFiniteRowsCandidate.deps.json',
    'modules/game-bridge/windows-ui-batch-draft/Prepare-FiniteRowsCandidate.ps1',
    'modules/game-bridge/windows-ui-batch-draft/Request-FiniteRows.ps1','LICENSE',
]
def check_project(source):
    root = ET.fromstring(source)
    assert root.findtext('.//AssemblyName') == 'FootballAssistant.WindowsFiniteRowsCandidate'
    assert root.findtext('.//EnableDefaultCompileItems') == 'false'
    items = [i for g in root.findall('ItemGroup') for i in g]
    assert all(i.tag == 'Compile' and set(i.attrib) <= {'Include','Link'} and not list(i) for i in items)
    assert len(items) == len(COMPILES) and {i.attrib['Include'] for i in items} == COMPILES
    assert not root.findall('Target') and not root.findall('Import')
def check_artifact(source):
    marker = 'name: bridge-windows-x64-FINITE-ROWS-OPT-IN-NO-CONFIG'
    assert source.count(marker) == 1
    block = source.split(marker)[1].split('path: |')[1].split('if-no-files-found:')[0]
    assert [line.strip() for line in block.splitlines() if line.strip()] == PATHS
    assert 'run: ./modules/game-bridge/windows-ui-batch-draft/Test-FiniteRowsRequestHelper.ps1' in source
    assert 'run: ./modules/game-bridge/windows-ui-batch-draft/Prepare-FiniteRowsCandidate.ps1' not in source
    assert 'run: ./modules/game-bridge/windows-ui-batch-draft/Request-FiniteRows.ps1' not in source
def reject(fn, value):
    try: fn(value)
    except AssertionError: return
    raise AssertionError('Isolation mutation accepted')
def main():
    project = (HERE/'FootballAssistant.WindowsFiniteRowsCandidate.csproj').read_text()
    workflow = (ROOT/'.github/workflows/windows-bridge-probe.yml').read_text()
    check_project(project); check_artifact(workflow)
    for path in COMPILES: assert (HERE/path).is_file(), path
    entry = (HERE/'FiniteRowsCandidateEntrypoint.cs').read_text()
    assert 'FiniteRowsCandidateHost' in entry and 'DiscoveryCandidateHost' not in entry
    prepare = (HERE/'Prepare-FiniteRowsCandidate.ps1').read_text()
    assert "schema_version = 4; mode = 'goalkeeper_rows0_3'" in prepare
    assert 'footballassistant.windows-finite-rows.json' in prepare and 'FootballAssistant.WindowsFiniteRowsCandidate.dll' in prepare
    assert 'GetFileInformationByHandle' in prepare and 'ReparsePoint' in prepare and 'Get-Process -Name fm' in prepare
    assert 'Start-Process' not in prepare
    for name in ('footballassistant.windows-finite-rows.json','finite-rows-request.json'): assert not (HERE/name).exists()
    reject(check_project,project.replace('<EnableDefaultCompileItems>false','<EnableDefaultCompileItems>true'))
    reject(check_project,project.replace('FiniteRowsCandidateHost.cs','DiscoveryCandidateHost.cs'))
    reject(check_project,project.replace('</ItemGroup>','<Content Include="*.json" /></ItemGroup>'))
    for path in ('build/windows-finite-rows/**','footballassistant.windows-finite-rows.json','finite-rows-request.json'):
        reject(check_artifact,workflow.replace(PATHS[0],path))
    print('Finite build/package static checks passed; six isolation mutations rejected. No configuration/manifest shipped.')
if __name__ == '__main__': main()
