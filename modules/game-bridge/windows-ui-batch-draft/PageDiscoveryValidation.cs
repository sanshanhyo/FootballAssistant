using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
namespace FootballAssistant.GameBridge;

// Same-capture display checks adapted from the pinned Mac projection contracts.
// This does not identify a team/player, current game date, visible pixels or an entire page.
internal static class PageDiscoveryValidation
{
    internal static bool TryValidate(DiscoveryResult? result,string profile)
    {
        if(!FiniteCaptureSelection.TryGet(profile,out var selection) || selection.Kind=="attributes" || result is null ||
            result.Status!="raw_diagnostics" || result.Reason!="approved_group_targets_complete" ||
            result.SelectionProfile!=profile || result.PageIdentityVerified || result.TraversalBounded ||
            result.PanelIndex!=0 || result.FocusPath!=selection.FocusRoot ||
            result.NativeOperations is <0 or >2048 || result.Nodes is <1 or >96 ||
            result.TotalRoots is <0 or >512 || result.PeakRoots is <0 or >64 ||
            !double.IsFinite(result.ElapsedMilliseconds) || result.ElapsedMilliseconds is <0 or >1000 ||
            result.Observations is null) return false;
        var paths=selection.GetPaths();
        if(result.Observations.Length!=paths.Length) return false;
        var raw=new string[paths.Length];
        for(var i=0;i<paths.Length;i++)
        {
            var item=result.Observations[i];
            if(item is null || item.Path!=paths[i] || item.Text is null || item.Text.Length is <1 or >128) return false;
            raw[i]=item.Text;
        }
        return selection.Kind switch { "tactics"=>Tactics(raw), "tactics_alignment"=>Tactics(raw), "next_match"=>NextMatch(raw),
            "schedule"=>Schedule(raw), _=>false };
    }
    private static bool Letter(char c)=>char.IsLetter(c);
    private static bool Number(char c)=>char.IsNumber(c);
    private static string? TacticalText(string raw)
    {
        var value=raw.Replace("\u200b","",StringComparison.Ordinal);
        return value.Length>0 && value==value.Trim() && value.All(c=>Letter(c)||Number(c)||c is ' ' or '-') ? value : null;
    }
    private static bool Tactics(string[] raw)
    {
        var values=raw.Select(TacticalText).ToArray();
        if(values.Any(v=>v is null) || values[3]!="队形") return false;
        var title=values[0]!; var style=values[1]!; var mentality=values[2]!;
        if(!(style+mentality).All(c=>Letter(c)||c==' ')) return false;
        var prefix=mentality=="防守" && title.StartsWith("偏向防守",StringComparison.Ordinal) ? "偏向防守" : mentality;
        var suffix=" - "+style;
        if(!title.StartsWith(prefix,StringComparison.Ordinal) || !title.EndsWith(suffix,StringComparison.Ordinal) ||
            title.Length<prefix.Length+suffix.Length) return false;
        var formation=title.Substring(prefix.Length,title.Length-prefix.Length-suffix.Length);
        if(formation!=formation.Trim() || formation.Contains(" - ",StringComparison.Ordinal)) return false;
        var match=Regex.Match(formation,@"\A([1-9](?:-[1-9]){1,4})(?: (.+))?\z",RegexOptions.CultureInvariant);
        if(!match.Success || match.Groups[1].Value.Split('-').Sum(int.Parse)!=10) return false;
        var descriptor=match.Groups[2];
        return !descriptor.Success || (char.IsLetterOrDigit(descriptor.Value[0]) &&
            char.IsLetterOrDigit(descriptor.Value[^1]) && descriptor.Value.Any(Letter));
    }
    private static string? NextText(string raw,bool markup)
    {
        var value=raw;
        if(markup && (value.Contains('<')||value.Contains('>')))
        {
            const string prefix="<color=\"#FFFFFF\"><link=\"0\"><style=\"Norml\">";
            const string suffix="</style></link></color>";
            if(!value.StartsWith(prefix,StringComparison.Ordinal)||!value.EndsWith(suffix,StringComparison.Ordinal)||
                value.Length<=prefix.Length+suffix.Length) return null;
            value=value.Substring(prefix.Length,value.Length-prefix.Length-suffix.Length);
            if(value.Contains('<')||value.Contains('>')) return null;
        }
        value=value.Replace("\u200b","",StringComparison.Ordinal);
        return value.Length>0 && value==value.Trim() && value.All(c=>Letter(c)||Number(c)||char.IsPunctuation(c)||c==' ') ? value : null;
    }
    private static bool NextMatch(string[] raw)
    {
        var title=NextText(raw[0],false); var opponent=NextText(raw[1],true);var competition=NextText(raw[2],true);
        if(title is null || opponent is null || competition is null || !opponent.Any(Letter)||!competition.Any(Letter)) return false;
        var match=Regex.Match(title,@"\A下一场比赛（([0-9]{4})-([1-9]|1[0-2])-([1-9]|[12][0-9]|3[01])）\z",RegexOptions.CultureInvariant);
        return match.Success && DateTime.TryParseExact(string.Join("-",match.Groups.Cast<Group>().Skip(1).Select(g=>g.Value)),
            "yyyy-M-d",CultureInfo.InvariantCulture,DateTimeStyles.None,out _);
    }
    // Strict existing Mac link/style/color grammar. Markup is display formatting, never identity.
    private static string? Plain(string raw)
    {
        var stack=new Stack<string>();var text=new StringBuilder();
        foreach(var part in Regex.Split(raw,@"(<[^<>]*>)",RegexOptions.CultureInvariant))
        {
            if(part.StartsWith('<'))
            {
                var close=Regex.Match(part,@"\A</(link|style|color)>\z",RegexOptions.CultureInvariant);
                if(close.Success)
                { if(stack.Count==0||stack.Pop()!=close.Groups[1].Value) return null; }
                else
                {
                    var tag=Regex.Match(part,"\\A<(link)=\"[0-9]{1,8}\">|<(style)=\"Norml\">|<(color)=(?:\"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\"|#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?)>\\z",RegexOptions.CultureInvariant);
                    if(!tag.Success || tag.Value!=part || stack.Count>=8) return null;
                    stack.Push(tag.Groups.Cast<Group>().Skip(1).First(g=>g.Success).Value);
                }
            }
            else { if(part.Contains('<')||part.Contains('>')) return null; text.Append(part); }
        }
        var value=text.ToString().Replace("\u200b","",StringComparison.Ordinal).Trim();
        if(stack.Count!=0||value.Length is <1 or >128 || value.Any(c=>char.GetUnicodeCategory(c) is
            UnicodeCategory.Control or UnicodeCategory.Format or UnicodeCategory.Surrogate or UnicodeCategory.PrivateUse or UnicodeCategory.OtherNotAssigned)) return null;
        return value;
    }
    private static bool Schedule(string[] raw)
    {
        if(raw[0]!="赛程安排") return false;
        var values=raw.Skip(1).Select(Plain).ToArray();
        if(values.Any(v=>v is null)||values[2] is not ("主" or "客")) return false;
        var date=Regex.Match(values[0]!,@"\A([0-9]{2})-([1-9]|1[0-2])-([1-9]|[12][0-9]|3[01])\z",RegexOptions.CultureInvariant);
        if(!date.Success) return false;
        var year=int.Parse(date.Groups[1].Value,CultureInfo.InvariantCulture);
        var month=int.Parse(date.Groups[2].Value,CultureInfo.InvariantCulture);
        var day=int.Parse(date.Groups[3].Value,CultureInfo.InvariantCulture);
        var days=new[]{31,year%4==0?29:28,31,30,31,30,31,31,30,31,30,31};
        return day<=days[month-1]; // Century/game-current-date deliberately remain unknown.
    }
}
