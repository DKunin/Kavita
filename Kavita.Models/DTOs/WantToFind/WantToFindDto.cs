#nullable enable
using System;

namespace Kavita.Models.DTOs.WantToFind;

public sealed record WantToFindDto
{
    public int Id { get; init; }
    public string Title { get; init; } = string.Empty;
    public string Authors { get; init; } = string.Empty;
    public string? Summary { get; init; }
    public string? Isbn { get; init; }
    public string? ExternalId { get; init; }
    public string? CoverUrl { get; init; }
    public string? SourceUrl { get; init; }
    public string? Notes { get; init; }
    public DateTime CreatedUtc { get; init; }
    public DateTime LastModifiedUtc { get; init; }
}
