using System.ComponentModel.DataAnnotations;

namespace Kavita.Models.DTOs.WantToFind;

public sealed record ResolveWantToFindDto
{
    [Required]
    public int WantToFindId { get; init; }

    [Required]
    public int SeriesId { get; init; }

    public bool AddToWantToRead { get; init; } = true;
}
