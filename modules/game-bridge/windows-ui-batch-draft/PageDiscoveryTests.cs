using FootballAssistant.GameBridge;

// Literal Mac selector fixture, owned buffers only. No real user/team/event values.
internal static class PageDiscoveryTests
{
    private static void Check(bool value,string message)
    {if(!value)throw new Exception("Page discovery fixture: "+message);}
    internal static void Run()
    {
        var at=DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context=new SmokeContext(12,"page-fixture",new string('a',64),new string('b',64),"FixtureWindow",34);
        var identity=new WindowsThreadIdentity(0,12,0,34,0,34,false)
        {WindowScanStatus="complete",WindowScanCount=1,WindowCandidates=new[]
            {new WindowsWindowDiagnostic(56,12,34,true,"FixtureWindow",true,0,true,true,10,10,0)}};
        DiscoveryPolicy Policy(string profile,string? focus=null)=>new(new(context,Guid.NewGuid(),0,
            focus??BatchTreeFixture.PageFocus(profile),at,at.AddSeconds(120),true,profile));
        DiscoveryResult Capture(DiscoveryPolicy policy,BatchTreeFixture fixture,Func<double>? elapsed=null,
            Func<WindowsThreadIdentity>? fresh=null)=>TargetedDiscoveryCollector.Run(policy,
            new(3,policy.Approval.Nonce,policy.ApprovalSha256),()=>new BatchNativeBackend(context.GameHash,fixture.Bind),
            fresh??(()=>identity),()=>at,elapsedForTest:elapsed??(()=>0))!;
        void Clean(BatchTreeFixture fixture,DiscoveryPolicy policy,DiscoveryResult result)
        {
            Check(policy.Terminal && fixture.LiveRoots==0 && fixture.RootCreates==fixture.RootFrees,"all roots released before terminal return");
            Check(result.NativeOperations==policy.TotalOperations && result.ElapsedMilliseconds==policy.TotalMilliseconds &&
                result.NativeOperations<=2048 && result.Nodes<=96 && result.TotalRoots<=512 && result.PeakRoots<=64 &&
                result.Observations.Length<=8 && !result.PageIdentityVerified,"unchanged operation/time/node/root/text safety ceilings");
        }
        var profiles=new[]{"tactics_current","next_match_card"}.Concat(Enumerable.Range(0,10).Select(i=>"schedule_row"+i));
        foreach(var profile in profiles)
        {
            Check(FiniteCaptureSelection.TryGet(profile,out var selection),"known fixed page plan admitted");
            var paths=BatchTreeFixture.PagePaths(profile);
            Check(selection.FocusRoot==BatchTreeFixture.PageFocus(profile) &&
                selection.GetPaths().OrderBy(p=>p,StringComparer.Ordinal).SequenceEqual(paths.OrderBy(p=>p,StringComparer.Ordinal)),
                "production plan equals independent literal Mac paths, regardless of semantic-array order");
            using var fixture=new BatchTreeFixture();fixture.BuildPageSelection(profile);
            var policy=Policy(profile);var guards=0;
            var result=Capture(policy,fixture,fresh:()=>{guards++;return identity;});
            var units=profile=="tactics_current"?1241:profile=="next_match_card"?817:1341;
            var nodes=profile=="tactics_current"?64:profile=="next_match_card"?41:69;
            var roots=profile=="tactics_current"?199:profile=="next_match_card"?129:215;
            Check(result.Status=="raw_diagnostics" && result.Observations.Select(o=>o.Path).SequenceEqual(paths.OrderBy(p=>p,StringComparer.Ordinal)) &&
                result.NativeOperations==units && result.Nodes==nodes && result.TotalRoots==roots &&
                result.PeakRoots==(profile=="tactics_current"?11:profile=="next_match_card"?15:33) && guards==units+nodes+3,
                "single-pass native trie exact units/nodes/roots/fresh guards");
            Check(PageDiscoveryValidation.TryValidate(result,profile),"all selected complete synthetic displays pass pinned semantics");
            Check(result.FocusEdges is null,"normal page profiles never acquire candidate-only edge traces");
            DiscoveryResult TextAt(string path,string text)=>result with {Observations=result.Observations
                .Select(o=>o.Path==path?o with {Text=text}:o).ToArray()};
            if(profile=="tactics_current")
            {
                Check(PageDiscoveryValidation.TryValidate(TextAt(paths[0],"均衡4-4-2 - 控\u200b球"),profile),"only observed tactical zero-width removal");
                Check(!PageDiscoveryValidation.TryValidate(TextAt(paths[0]," 均衡4-4-2 - 控球"),profile),"tactical text cannot be trimmed into validity");
            }
            else
            {
                var textPath=profile=="next_match_card"?paths[1]:paths[2];
                Check(PageDiscoveryValidation.TryValidate(TextAt(textPath,"<color=\"#FFFFFF\"><link=\"0\"><style=\"Norml\">TEST OPPONENT</style></link></color>"),profile),
                    "only approved Mac display wrapper is accepted, never an entity ID");
                Check(!PageDiscoveryValidation.TryValidate(TextAt(textPath,"<script>TEST OPPONENT</script>"),profile),"arbitrary markup rejected");
            }
            Check(fixture.PanelOpens==1 && fixture.TextReads.SequenceEqual(result.Observations.Select(o=>fixture.NodeAt(o.Path))),
                "only selected text getters, one panel, no sibling or unrelated-row fallback");
            var edges=new List<(nint Parent,int Index)>();
            void Visit(string prefix)
            {
                foreach(var index in paths.Where(p=>prefix.Length==0||p.StartsWith(prefix+"/",StringComparison.Ordinal))
                    .Select(p=>p[(prefix.Length==0?0:prefix.Length+1)..].Split('/')[0]).Select(int.Parse).Distinct().OrderBy(i=>i))
                {
                    edges.Add((fixture.NodeAt(prefix),index));var next=prefix.Length==0?index.ToString():prefix+"/"+index;
                    if(!paths.Contains(next))Visit(next);
                }
            }
            Visit("");
            Check(edges.Count==nodes-1 && fixture.ChildEdges.SequenceEqual(edges),"every selected edge exactly once; no traversal of available other rows");
            if(profile.StartsWith("schedule_row",StringComparison.Ordinal))
            {
                var row=int.Parse(profile[12..]);
                var parent=BatchTreeFixture.PageFocus(profile)+"/0/0/0/0/0/0/0/0/1/1/0/1/0/0/0/2/0/0";
                Check(fixture.ChildEdges.Where(e=>e.Parent==fixture.NodeAt(parent)).Select(e=>e.Index).SequenceEqual(new[]{row}),
                    "all ten rows available, only approved schedule index obtained");
            }
            Check(!PageDiscoveryValidation.TryValidate(result with{Observations=result.Observations[..^1]},profile),"missing display rejects whole semantic group");
            Check(!PageDiscoveryValidation.TryValidate(result with{Observations=result.Observations.Append(result.Observations[0]).ToArray()},profile),"duplicate path rejects semantics");
            Check(!PageDiscoveryValidation.TryValidate(result,profile=="tactics_current"?"next_match_card":"tactics_current"),"another page plan cannot rebind result");
            Clean(fixture,policy,result);
            var before=fixture.RootCreates;
            Check(TargetedDiscoveryCollector.Run(policy,new(3,policy.Approval.Nonce,policy.ApprovalSha256),
                ()=>throw new Exception("replay must not bind"),()=>identity,()=>at,elapsedForTest:()=>0) is null && fixture.RootCreates==before,"no automatic retry after success");
            Console.WriteLine($"Page {profile}: units={units},nodes={nodes},roots={roots},guards={guards}; synthetic elapsed0, no live claim.");
        }
        var combined=BatchTreeFixture.PagePaths("schedule_row0").Concat(BatchTreeFixture.PagePaths("schedule_row1")).Distinct().ToArray();
        var combinedNodes=new HashSet<string>{""};
        foreach(var path in combined)
        {var parts=path.Split('/');for(var i=1;i<=parts.Length;i++)combinedNodes.Add(string.Join("/",parts.Take(i)));}
        Check(combined.Length==9 && combinedNodes.Count==98,"two schedule rows exceed both96nodes and8texts; no native two-row plan exposed");
        Check(BatchTreeFixture.TacticsPageRoot.Split('/').Length==35,"tactics requires exact35-edge focus exception");
        foreach(var altered in new[]{BatchTreeFixture.TacticsPageRoot[..^1]+"1",string.Join("/",Enumerable.Repeat("0",35)),BatchTreeFixture.TacticsPageRoot+"/0"})
        {
            var denied=false;try{_=Policy("tactics_current",altered);}catch(ArgumentException){denied=true;}
            Check(denied,"arbitrary same-depth or deeper focus cannot use tactics fixed exception");
        }
        Check(!FiniteCaptureSelection.TryGet("schedule_row10",out _) && !FiniteCaptureSelection.TryGet("schedule_row00",out _) &&
            !FiniteCaptureSelection.TryGet("schedule_rows0_1",out _),"no arbitrary indices or overbudget two-row schedule plan");
        Check(!TargetedDiscoveryCollector.IsAllowedTargetPath(TargetedDiscoveryCollector.FocusRoot+string.Concat(Enumerable.Repeat("/0",24))),
            "global49 remains rejected by fixed-target depth gate");
        foreach(var profile in new[]{"tactics_current","next_match_card","schedule_row0"})
        foreach(var failure in new[]{"hidden","missing","nontext","badtitle","semantic","cleanup","work","hard","finalguard"})
        {
            using var fixture=new BatchTreeFixture();fixture.BuildPageSelection(profile);var paths=BatchTreeFixture.PagePaths(profile);
            if(failure=="hidden")fixture.HiddenNodes.Add(fixture.NodeAt(paths[^1]));
            if(failure=="missing")fixture.Children[fixture.NodeAt(paths[^1][..paths[^1].LastIndexOf('/')])].Clear();
            if(failure=="nontext")fixture.SetNodeText(paths[^1],null);
            if(failure=="badtitle")fixture.SetNodeText(profile=="tactics_current"?paths[3]:paths[0],"TEST WRONG TITLE");
            if(failure=="semantic")fixture.SetNodeText(profile=="tactics_current"?paths[0]:profile=="next_match_card"?paths[0]:paths[1],
                profile=="tactics_current"?"均衡4-4-3 - 控球":profile=="next_match_card"?"下一场比赛（2030-2-30）":"30-2-30");
            if(failure=="cleanup")fixture.FailFirstFree=true;
            var policy=Policy(profile);
            var result=Capture(policy,fixture,elapsed:()=>failure=="work"&&fixture.TextReads.Count>0?801:
                failure=="hard"&&fixture.RootCreates>0&&fixture.LiveRoots==0?1001:0,
                fresh:()=>failure=="finalguard"&&fixture.RootCreates>0&&fixture.LiveRoots==0?identity with{WindowScanStatus="failed"}:identity);
            if(failure is "badtitle" or "semantic") Check(result.Status=="raw_diagnostics"&&!PageDiscoveryValidation.TryValidate(result,profile),"raw getters do not imply semantic page success");
            else Check(result.Status=="terminal_failure"&&result.Observations.Length==0,"failure clears entire selected page set: "+failure);
            Clean(fixture,policy,result);
        }
        // One explicit alignment hypothesis only: original selectors with edge14 changed1→0.
        const string alignment="tactics_alignment_candidate";
        var alignmentPaths=BatchTreeFixture.PagePaths(alignment);
        var originalParts=BatchTreeFixture.TacticsPageRoot.Split('/');
        var candidateParts=BatchTreeFixture.TacticsAlignmentRoot.Split('/');
        Check(originalParts.Length==35 && candidateParts.Length==35 && originalParts[14]=="1" && candidateParts[14]=="0" &&
            Enumerable.Range(0,35).Where(i=>originalParts[i]!=candidateParts[i]).SequenceEqual(new[]{14}),
            "independent literal root changes exactly the approved zero-based edge14");
        Check(FiniteCaptureSelection.TryGet(alignment,out var alignedSelection) && alignedSelection.Kind=="tactics_alignment" &&
            alignedSelection.FocusRoot==BatchTreeFixture.TacticsAlignmentRoot &&
            alignedSelection.GetPaths().SequenceEqual(alignmentPaths),"candidate is separately named, with exact unchanged fixed suffixes");
        var standardMethodLookups=0;var standardUnits=0;
        foreach(var inherited in new[]{false,true})
        {
            using var fixture=new BatchTreeFixture {InheritedContainerMethods=inherited};fixture.BuildPageSelection(alignment);
            var parent=fixture.NodeAt(BatchTreeFixture.TacticsAlignmentParent);
            Check(fixture.Children[parent].Count==1,"fixture actually exposes one child at evidenced parent");
            var policy=Policy(alignment);var guards=0;
            var result=Capture(policy,fixture,fresh:()=>{guards++;return identity;});
            Check(result.Status=="raw_diagnostics" && result.Nodes==64 && result.TotalRoots==199 && result.PeakRoots==11 &&
                result.Observations.Select(o=>o.Path).SequenceEqual(alignmentPaths) &&
                PageDiscoveryValidation.TryValidate(result,alignment),"all four generic synthetic displays pass candidate-only grammar");
            Check(!PageDiscoveryValidation.TryValidate(result,"tactics_current"),"alignment capture never becomes normal tactics by rebinding");
            Check(result.FocusEdges is {Length:35} && result.FocusEdges.Select(e=>e.Depth).SequenceEqual(Enumerable.Range(0,35)) &&
                result.FocusEdges.Select(e=>e.RequestedChildIndex).SequenceEqual(candidateParts.Select(int.Parse)) &&
                result.FocusEdges.All(e=>e.Stage==5 && e.ObservedChildCount>=1) && result.FocusEdges[14].ObservedChildCount==1,
                "bounded numeric edge trace records each successful known count/obtained child");
            Check(fixture.ChildEdges.Where(e=>e.Parent==parent).Select(e=>e.Index).SequenceEqual(new[]{0}) &&
                fixture.TextReads.SequenceEqual(alignmentPaths.Select(fixture.NodeAt)),"sole child0 and four exact getters only");
            var expectedEdges=new List<(nint Parent,int Index)>();
            void Walk(string prefix)
            {
                foreach(var index in alignmentPaths.Where(path=>prefix.Length==0||path.StartsWith(prefix+"/",StringComparison.Ordinal))
                    .Select(path=>path[(prefix.Length==0?0:prefix.Length+1)..].Split('/')[0]).Select(int.Parse).Distinct().OrderBy(i=>i))
                {
                    expectedEdges.Add((fixture.NodeAt(prefix),index));var next=prefix.Length==0?index.ToString():prefix+"/"+index;
                    if(!alignmentPaths.Contains(next))Walk(next);
                }
            }
            Walk("");
            Check(expectedEdges.Count==63 && fixture.ChildEdges.SequenceEqual(expectedEdges),"no unselected siblings or original edge1 fallback obtained");
            if(!inherited)
            {
                standardMethodLookups=fixture.MethodLookups;standardUnits=result.NativeOperations;
                Check(result.NativeOperations==1241 && guards==1308,"numeric trace adds no native calls or fresh checks");
            }
            else
            {
                Check(fixture.ParentLookups>0 && fixture.MethodLookups>standardMethodLookups &&
                    result.NativeOperations==standardUnits+fixture.ParentLookups+fixture.MethodLookups-standardMethodLookups &&
                    guards==result.NativeOperations+result.Nodes+3,"inherited extra units equal actual fixture lookup exports, not a fabricated measured constant");
                Console.WriteLine($"Alignment inherited fixture: units={result.NativeOperations},parents={fixture.ParentLookups},methods={fixture.MethodLookups},guards={guards}; owned delegates only.");
            }
            Clean(fixture,policy,result);
            Check(TargetedDiscoveryCollector.Run(policy,new(3,policy.Approval.Nonce,policy.ApprovalSha256),
                ()=>throw new Exception("no retry"),()=>identity,()=>at,elapsedForTest:()=>0) is null,"candidate remains one-shot after success");
        }
        foreach(var failure in new[]{"count0","count2","hidden","nullchild","suffix","semantic","guard","cleanup"})
        {
            using var fixture=new BatchTreeFixture {InheritedContainerMethods=true};fixture.BuildPageSelection(alignment);
            var parent=fixture.NodeAt(BatchTreeFixture.TacticsAlignmentParent);
            if(failure=="count0")fixture.Children[parent].Clear();
            if(failure=="count2")fixture.Children[parent].Add(fixture.NodeAt("0/0"));
            if(failure=="hidden")fixture.HiddenNodes.Add(parent);
            if(failure=="nullchild")fixture.NullChildEdges.Add((parent,0));
            nint wrongSuffixParent=0;
            if(failure=="suffix")
            {
                wrongSuffixParent=fixture.NodeAt(alignmentPaths[0][..alignmentPaths[0].LastIndexOf('/')]);
                fixture.Children[wrongSuffixParent].Add(fixture.Children[wrongSuffixParent][0]);
                fixture.Children[wrongSuffixParent][0]=fixture.NodeAt("0/0");
            }
            if(failure=="semantic")fixture.SetNodeText(alignmentPaths[0],"均衡4-4-3 - 控球");
            if(failure=="cleanup")fixture.FailFirstFree=true;
            var policy=Policy(alignment);
            var result=Capture(policy,fixture,fresh:()=>failure=="guard"&&fixture.ChildEdges.Count>=14?
                identity with{WindowScanStatus="failed"}:identity);
            var semantic=PageDiscoveryValidation.TryValidate(result,alignment);
            if(failure=="semantic")Check(result.Status=="raw_diagnostics"&&!semantic,"native text success cannot imply aligned tactical semantic success");
            else Check(result.Status=="terminal_failure"&&result.Observations.Length==0,"candidate failure discards all selected text: "+failure);
            if(failure is "count0" or "count2")
                Check(result.Reason=="alignment_parent_shape_changed" && !fixture.ChildEdges.Any(e=>e.Parent==parent) &&
                    result.FocusEdges is {Length:15} && result.FocusEdges[14].Depth==14 && result.FocusEdges[14].RequestedChildIndex==0 &&
                    result.FocusEdges[14].ObservedChildCount==(failure=="count0"?0:2) && result.FocusEdges[14].Stage==3,
                    "sole-child shape checked after actual count, before any get_Item or alternate sibling");
            if(failure=="hidden")Check(result.FocusEdges is {Length:15} && result.FocusEdges[14].Stage==2 &&
                result.FocusEdges[14].ObservedChildCount==-1,"hidden ancestor does not invent an unobserved child count");
            if(failure=="nullchild")Check(result.FocusEdges is {Length:15} && result.FocusEdges[14].Stage==4 &&
                result.FocusEdges[14].ObservedChildCount==1,"null child preserves attempted-stage rather than claiming obtained");
            if(failure=="suffix")Check(!fixture.ChildEdges.Contains((wrongSuffixParent,1)),"wrong suffix never hunts adjacent existing target");
            var publication=DiscoveryPublication.Create(result,false);
            Check(publication.Result is null && ReferenceEquals(publication.FocusEdges,result.FocusEdges) &&
                ReferenceEquals(publication.FocusDiagnostic,result.FocusDiagnostic),"rejected publication retains only numeric focus evidence separately");
            var json=System.Text.Json.JsonSerializer.Serialize(publication);
            Check(json.Contains("\"focus_edges\"") && !json.Contains("均衡") && !json.Contains("Text"),"failure publication includes bounded numeric trace, never raw texts");
            using(var encoded=System.Text.Json.JsonDocument.Parse(json))
            {
                var trace=encoded.RootElement.GetProperty("focus_edges");
                Check(trace.ValueKind==System.Text.Json.JsonValueKind.Array && trace.GetArrayLength()<=35,
                    "serialized candidate trace has at most35 bounded entries");
                foreach(var edge in trace.EnumerateArray())
                {
                    var properties=edge.EnumerateObject().ToArray();
                    Check(properties.Length==4 && properties.All(property=>
                        new[]{"Depth","RequestedChildIndex","ObservedChildCount","Stage"}.Contains(property.Name) &&
                        property.Value.ValueKind==System.Text.Json.JsonValueKind.Number && property.Value.TryGetInt32(out _)),
                        "edge serialization contains exactly four numeric fields, no paths/pointers/text");
                }
            }
            Clean(fixture,policy,result);
        }
        {
            using var fixture=new BatchTreeFixture();fixture.BuildPageSelection(alignment);
            var normal=Policy("tactics_current");var result=Capture(normal,fixture);
            var parent=fixture.NodeAt(BatchTreeFixture.TacticsAlignmentParent);
            Check(result.Status=="terminal_failure" && result.Observations.Length==0 && result.FocusEdges is null &&
                !fixture.ChildEdges.Any(edge=>edge.Parent==parent),"normal tactics never silently switches old requestededge1 to candidatechild0");
            Clean(fixture,normal,result);
            var rejected=false;
            try { _=Policy(alignment,BatchTreeFixture.TacticsAlignmentRoot+"/0"); } catch(ArgumentException) { rejected=true; }
            Check(rejected,"candidate request cannot override the fixed remaining suffix/root");
        }
    }
}
