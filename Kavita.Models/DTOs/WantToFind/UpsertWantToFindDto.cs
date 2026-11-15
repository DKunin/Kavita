#nullable enable
using System.ComponentModel.DataAnnotations;

namespace Kavita.Models.DTOs.WantToFind;

public sealed record UpsertWantToFindDto
{
    public int Id { get; init; }

    [Required(AllowEmptyStrings = false)]
    [MaxLength(256)]
    public required string Title { get; init; }

    [MaxLength(1024)]
    public string Authors { get; init; } = string.Empty;

    public string? Summary { get; init; }

    [MaxLength(64)]
    public string? Isbn { get; init; }

    [MaxLength(256)]
    public string? ExternalId { get; init; }

    [MaxLength(2048)]
    public string? CoverUrl { get; init; }

    [MaxLength(2048)]
    public string? SourceUrl { get; init; }

    public string? Notes { get; init; }
}
