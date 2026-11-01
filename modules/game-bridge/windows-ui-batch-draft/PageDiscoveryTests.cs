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
            Check(result.FocusEdges is null && result.Topology is null,"normal page profiles never acquire candidate-only edge traces");
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
        // Independent fixed diagnostic roots; no reuse of production selector construction.
        foreach(var profile in new[]{"tactics_sibling12","tactics_sibling7","tactics_sibling4"})
        {
            var focus=BatchTreeFixture.SiblingFocus(profile);var depth=focus.Split('/').Length;
            Check(FiniteCaptureSelection.TryGet(profile,out var probe) && probe.Kind=="tactics_sibling_probe" &&
                probe.FocusRoot==focus,"only three literal approved sibling roots");
            foreach(var scenario in new[]{"empty","text","count0","count1","count3","hiddenancestor","nullchild",
                "hiddennode","width","depth","textcap","work","operations","cleanup","guard","finalguard","hard"})
            {
                using var fixture=new BatchTreeFixture {InheritedContainerMethods=true};
                var relative=scenario=="width"?new[]{"8"}:scenario=="depth"?
                    new[]{string.Join("/",Enumerable.Repeat("0",49-depth))}:
                    scenario=="textcap"?Enumerable.Range(0,8).Select(i=>i.ToString()).ToArray():
                    scenario=="operations"?Enumerable.Range(0,8).SelectMany(i=>Enumerable.Range(0,8).SelectMany(j=>Enumerable.Range(0,8).Select(k=>$"{i}/{j}/{k}"))).ToArray():
                    scenario is "text" or "work" or "finalguard" or "hard"?new[]{"0"}:Array.Empty<string>();
                fixture.BuildSiblingProbe(profile,relative);
                var parent=fixture.NodeAt(focus[..focus.LastIndexOf('/')]);var root=fixture.NodeAt(focus);
                if(scenario=="count0")fixture.Children[parent].Clear();
                if(scenario=="count1")fixture.Children[parent].RemoveAt(1);
                if(scenario=="count3")fixture.Children[parent].Add(fixture.NodeAt("0/0"));
                if(scenario=="hiddenancestor")fixture.HiddenNodes.Add(parent);
                if(scenario=="nullchild")fixture.NullChildEdges.Add((parent,1));
                if(scenario=="hiddennode")fixture.HiddenNodes.Add(root);
                if(scenario is "text" or "work" or "finalguard" or "hard")fixture.SetNodeText(focus+"/0","TEST RAW ANCHOR");
                if(scenario=="textcap")foreach(var path in relative)fixture.SetNodeText(focus+"/"+path,"TEST RAW "+path);
                if(scenario=="cleanup")fixture.FailFirstFree=true;
                var policy=Policy(profile);var guards=0;
                var result=Capture(policy,fixture,elapsed:()=>scenario=="work"&&fixture.TextReads.Count>0?801:
                    scenario=="hard"&&fixture.RootCreates>0&&fixture.LiveRoots==0?1001:0,
                    fresh:()=>{guards++;return (scenario=="guard"&&fixture.ChildEdges.Count>=depth ||
                        scenario=="finalguard"&&fixture.RootCreates>0&&fixture.LiveRoots==0)?
                        identity with{WindowScanStatus="failed"}:identity;});
                var failed=scenario is "count0" or "count1" or "count3" or "hiddenancestor" or "nullchild" or "cleanup" or "guard" or "finalguard" or "hard";
                Check(result.Status==(failed?"terminal_failure":"raw_diagnostics"),"sibling scenario status: "+scenario);
                Check(PageDiscoveryValidation.TryValidate(result,profile)==!failed &&
                    !PageDiscoveryValidation.TryValidate(result,"tactics_current"),
                    "host accepts only bounded raw probe envelope, never normal tactical fields");
                if(!failed)
                {
                    Check(!PageDiscoveryValidation.TryValidate(result with { FocusPath="0/6" },profile) &&
                        !PageDiscoveryValidation.TryValidate(result with { Observations=new[]{new DiscoveryText("0/6","TEST")} },profile) &&
                        !PageDiscoveryValidation.TryValidate(result with { TraversalBounded=!result.TraversalBounded },profile),
                        "probe validation binds exact scope and truthful bounded reason");
                }
                Check(result.Topology is not null && result.Topology.Length<=96 && result.FocusEdges is not null && result.FocusEdges.Length<=35,
                    "numeric traces allocated only within fixed bounds");
                if(failed)Check(result.Observations.Length==0,"failed probes discard provisional text");
                if(scenario is "count0" or "count1" or "count3")
                    Check(result.Reason=="sibling_parent_shape_changed" && !fixture.ChildEdges.Any(e=>e.Parent==parent) &&
                        result.FocusEdges!.Last().ObservedChildCount==int.Parse(scenario[^1..]) && result.FocusEdges.Last().Stage==3,
                        "actual parent count must be exactly2 before obtaining child1");
                if(scenario=="empty")Check(result.Observations.Length==0 && !result.TraversalBounded &&
                    result.Topology is {Length:1} && result.Topology[0]==new DiscoveryTopologyNode(-1,-1,depth,1,0,0,4),
                    "empty success requires actual visible/type/count reads, not absence of text alone");
                if(scenario=="text")Check(result.Observations.Length==1 && result.Observations[0].Path==focus+"/0" &&
                    result.Topology is {Length:2} && result.Topology[1].ParentRecordIndex==0 && result.Topology[1].ChildEdge==0,
                    "raw arbitrary text and numeric parent edge retained without tactical semantic claims");
                if(scenario is "hiddennode" or "width" or "depth" or "textcap" or "work" or "operations")
                    Check(result.TraversalBounded,"uninspected visible/hidden contents always explicitly partial: "+scenario);
                if(scenario=="hiddennode")Check(result.Topology![0].Visible==0 && result.Topology[0].TextElement==-1 &&
                    result.Topology[0].ChildCount==-1 && result.Topology[0].Stage==2,"hidden fields remain unknown");
                if(scenario=="width")Check(result.Topology![0].ChildCount==9 && !fixture.ChildEdges.Contains((root,8)),"first8 only, no child8 prefetch");
                if(scenario=="depth")Check(result.Topology!.Max(n=>n.GlobalDepth)==48 &&
                    result.Topology.Last().ChildCount==1 && !fixture.ChildEdges.Any(e=>e.Parent==fixture.NodeAt(focus+"/"+string.Join("/",Enumerable.Repeat("0",48-depth)))) ,
                    "depth48 inspected; depth49 child never obtained");
                if(scenario=="textcap")Check(result.Observations.Length==8 && result.Topology!.Last().ChildCount==-1 &&
                    result.Topology.Last().Stage==3,"text cap stops before count without invented zero");
                if(scenario=="operations")Check(result.NativeOperations>=1792 && result.NativeOperations<2048 && result.Nodes<96,
                    "cooperative operations stop distinct from hard failure");
                Check(!fixture.ChildEdges.Contains((parent,0)),"never fallback to original child0 spine or another root");
                foreach(var node in result.Topology!)Check(node.ParentRecordIndex>=-1 && node.ParentRecordIndex<result.Topology.Length &&
                    node.GlobalDepth>=depth && node.GlobalDepth<=48 && node.Visible is >=-1 and <=1 && node.TextElement is >=-1 and <=1,
                    "bounded numeric topology values");
                var publication=DiscoveryPublication.Create(result,false);
                Check(publication.Result is null && ReferenceEquals(publication.Topology,result.Topology),"failure publication preserves numeric topology only");
                using(var json=System.Text.Json.JsonDocument.Parse(System.Text.Json.JsonSerializer.Serialize(publication)))
                    foreach(var node in json.RootElement.GetProperty("topology").EnumerateArray())
                        Check(node.EnumerateObject().Count()==10 && node.EnumerateObject().All(p=>p.Value.TryGetInt32(out _)),"topology is ten integers only");
                Clean(fixture,policy,result);
                Check(TargetedDiscoveryCollector.Run(policy,new(3,policy.Approval.Nonce,policy.ApprovalSha256),
                    ()=>throw new Exception("replay"),()=>identity,()=>at,elapsedForTest:()=>0) is null,"probe cannot retry in consumed request");
                Console.WriteLine($"Sibling {profile}/{scenario}: units={result.NativeOperations},nodes={result.Nodes},roots={result.TotalRoots},guards={guards}; owned fixture only.");
            }
        }
        foreach(var profile in new[]{"tactics_root_census","tactics_frontier35"})
        foreach(var scenario in new[]{"complete","empty","blank","zero","hidden","countlow","counthigh","work","hard","guard","cleanup"})
        {
            var census=profile=="tactics_root_census";var focus=census?"0":BatchTreeFixture.FrontierRoot;
            Check(FiniteCaptureSelection.TryGet(profile,out var selected) && selected.Kind=="tactics_frontier_probe" && selected.FocusRoot==focus,
                "two fixed frontier plans use independent literal roots");
            using var fixture=new BatchTreeFixture {InheritedContainerMethods=true};
            fixture.BuildFrontier(census,census?"0/0":"0");
            var root=fixture.NodeAt(focus);var target=fixture.NodeAt(focus+"/0");
            fixture.SetNodeText(focus+"/0",scenario=="blank"?"   ":"TEST RAW DISPLAY");
            if(!census&&scenario=="empty"){fixture.Children[root].Clear();fixture.SetNodeText(focus,null);}
            if(scenario=="zero")fixture.ZeroBoundsNodes.Add(target);
            if(scenario=="hidden")fixture.HiddenNodes.Add(target);
            var gated=census?root:fixture.NodeAt(focus[..focus.LastIndexOf('/')]);
            if(scenario=="countlow")fixture.Children[gated].RemoveAt(fixture.Children[gated].Count-1);
            if(scenario=="counthigh")fixture.Children[gated].Add(fixture.NodeAt("0/0"));
            if(scenario=="cleanup")fixture.FailFirstFree=true;
            var policy=Policy(profile);var guards=0;
            var result=Capture(policy,fixture,elapsed:()=>scenario=="work"&&fixture.Invocations.Count(x=>x=="get_worldBound")>0?801:
                scenario=="hard"&&fixture.RootCreates>0&&fixture.LiveRoots==0?1001:0,
                fresh:()=>{guards++;return scenario=="guard"&&fixture.RootCreates>0&&fixture.LiveRoots==0?
                    identity with{WindowScanStatus="failed"}:identity;});
            var failed=scenario is "countlow" or "counthigh" or "hard" or "guard" or "cleanup";
            Check(result.Status==(failed?"terminal_failure":"raw_diagnostics"),"frontier status: "+profile+"/"+scenario);
            Check(PageDiscoveryValidation.TryValidate(result,profile)==!failed &&
                !PageDiscoveryValidation.TryValidate(result,"tactics_current"),"host validates raw frontier envelope only, never normal tactics");
            if(census && !failed)Check(!PageDiscoveryValidation.TryValidate(result with
                { Observations=new[]{new DiscoveryText("0/0","FORBIDDEN CENSUS TEXT")} },profile),
                "census publication cannot accidentally admit text observations");
            Check(result.Topology is not null && result.Topology.Length<=96 && result.FocusEdges is not null,"bounded numeric publication always available");
            if(failed)Check(result.Observations.Length==0,"all hard failures discard raw texts");
            if(scenario is "countlow" or "counthigh")Check(!fixture.ChildEdges.Any(e=>e.Parent==gated) &&
                result.Reason==(census?"census_root_shape_changed":"frontier_parent_shape_changed"),"shape gate occurs before any selected child");
            if(census)
            {
                Check(fixture.TextReads.Count==0 && result.Observations.Length==0,"census never calls text getters even for eligible text nodes");
                Check(fixture.ChildEdges.All(e=>e.Parent==fixture.NodeAt("")||e.Parent==root),"census never obtains descendants");
                if(scenario is "complete" or "empty" or "blank" or "zero" or "hidden")
                    Check(result.Topology!.Length==21 && fixture.ChildEdges.Where(e=>e.Parent==root).Select(e=>e.Index).SequenceEqual(Enumerable.Range(0,20)),
                        "exactly20 immediate children sequentially scoped, not generic width growth");
                Check(result.Topology!.All(n=>n.TextReadCompleted==-1&&n.TextLength==-1),"census never invents text eligibility reads");
            }
            else
            {
                Check(fixture.ChildEdges.All(e=>e.Parent!=gated||e.Index==1),"frontier never samples original child0 or another frontier");
                if(scenario=="complete")Check(result.Observations.Length==1 && result.Observations[0].Text=="TEST RAW DISPLAY" &&
                    result.Topology!.Last().BoundsEligible==1 && result.Topology.Last().TextReadCompleted==1 &&
                    result.Topology.Last().TextLength==16,"existing getter length is copied UTF16 length, not semantic eligibility");
                if(scenario=="blank")Check(result.Observations.Length==0 && result.Topology!.Last().TextReadCompleted==1 &&
                    result.Topology.Last().TextLength==3,"blank getter completion distinguished from unattempted getter");
                if(scenario=="empty")Check(result.Observations.Length==0 && !result.TraversalBounded && result.Topology![0].ChildCount==0,
                    "actual count0 empty frontier is complete only within approved subtree");
            }
            if(scenario=="zero")Check(result.Topology!.Single(n=>n.ParentRecordIndex==0&&n.ChildEdge==0).BoundsEligible==0 &&
                fixture.TextReads.Count==0,"zero bounds prevents text getter and records ineligibility");
            if(scenario=="hidden")Check(result.TraversalBounded && result.Topology!.Single(n=>n.ParentRecordIndex==0&&n.ChildEdge==0).BoundsEligible==-1,
                "hidden bounds unknown, traversal explicitly partial");
            if(scenario=="work")Check(result.TraversalBounded,"cooperative stop returns explicitly bounded raw diagnostics");
            var publication=DiscoveryPublication.Create(result,false);
            using(var json=System.Text.Json.JsonDocument.Parse(System.Text.Json.JsonSerializer.Serialize(publication)))
                foreach(var node in json.RootElement.GetProperty("topology").EnumerateArray())
                    Check(node.EnumerateObject().Count()==10 && node.EnumerateObject().All(p=>p.Value.TryGetInt32(out _)),"all10 topology fields numeric on rejected publication");
            Clean(fixture,policy,result);
            Check(TargetedDiscoveryCollector.Run(policy,new(3,policy.Approval.Nonce,policy.ApprovalSha256),
                ()=>throw new Exception("replay"),()=>identity,()=>at,elapsedForTest:()=>0) is null,"fixed frontier request cannot replay");
            if(!failed)Check(guards==result.NativeOperations+result.Nodes+3,"numeric diagnostics add no fresh checks or hidden native calls");
            Console.WriteLine($"Frontier {profile}/{scenario}: units={result.NativeOperations},nodes={result.Nodes},roots={result.TotalRoots},peak={result.PeakRoots},guards={guards}; inherited owned fixture only.");
        }
    }
}
