using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Kavita.API.Database;
using Kavita.API.Repositories;
using Kavita.Models.Constants;
using Kavita.Models.DTOs.WantToFind;
using Kavita.Models.Entities.User;
using Kavita.Server.Attributes;
using Microsoft.AspNetCore.Mvc;

namespace Kavita.Server.Controllers;

/// <summary>
/// Metadata-only titles the current user wants to acquire.
/// </summary>
[Route("api/want-to-find")]
public class WantToFindController(IUnitOfWork unitOfWork) : BaseApiController
{
    [HttpGet]
    public async Task<ActionResult<IList<WantToFindDto>>> GetAll()
    {
        return Ok(await unitOfWork.WantToFindRepository.GetDtosAsync(UserId, HttpContext.RequestAborted));
    }

    [HttpPost("create")]
    [DisallowRole(PolicyConstants.ReadOnlyRole)]
    public async Task<ActionResult<WantToFindDto>> Create(UpsertWantToFindDto dto)
    {
        if (!HasValidUrls(dto)) return BadRequest("Cover and source URLs must use HTTP or HTTPS.");

        var item = new AppUserWantToFind { AppUserId = UserId, Title = string.Empty };
        Apply(item, dto);
        unitOfWork.WantToFindRepository.Add(item);
        await unitOfWork.CommitAsync(HttpContext.RequestAborted);

        return Ok(await GetDto(item.Id));
    }

    [HttpPost("update")]
    [DisallowRole(PolicyConstants.ReadOnlyRole)]
    public async Task<ActionResult<WantToFindDto>> Update(UpsertWantToFindDto dto)
    {
        if (!HasValidUrls(dto)) return BadRequest("Cover and source URLs must use HTTP or HTTPS.");

        var item = await unitOfWork.WantToFindRepository.GetAsync(dto.Id, UserId, HttpContext.RequestAborted);
        if (item == null) return NotFound();

        Apply(item, dto);
        unitOfWork.WantToFindRepository.Update(item);
        await unitOfWork.CommitAsync(HttpContext.RequestAborted);

        return Ok(await GetDto(item.Id));
    }

    [HttpDelete]
    [DisallowRole(PolicyConstants.ReadOnlyRole)]
    public async Task<ActionResult> Delete(int wantToFindId)
    {
        var item = await unitOfWork.WantToFindRepository.GetAsync(wantToFindId, UserId, HttpContext.RequestAborted);
        if (item == null) return NotFound();

        unitOfWork.WantToFindRepository.Remove(item);
        await unitOfWork.CommitAsync(HttpContext.RequestAborted);
        return NoContent();
    }

    /// <summary>
    /// Removes a metadata-only item after it is matched to an accessible library series.
    /// </summary>
    [HttpPost("resolve")]
    [DisallowRole(PolicyConstants.ReadOnlyRole)]
    public async Task<ActionResult> Resolve(ResolveWantToFindDto dto)
    {
        var ct = HttpContext.RequestAborted;
        var item = await unitOfWork.WantToFindRepository.GetAsync(dto.WantToFindId, UserId, ct);
        if (item == null) return NotFound();
        if (!await unitOfWork.UserRepository.HasAccessToSeries(UserId, [dto.SeriesId], ct)) return NotFound();

        if (dto.AddToWantToRead)
        {
            var user = await unitOfWork.UserRepository.GetUserByIdAsync(UserId, AppUserIncludes.WantToRead, ct);
            if (user == null) return Unauthorized();

            if (!user.WantToRead.Any(w => w.SeriesId == dto.SeriesId))
            {
                user.WantToRead.Add(new AppUserWantToRead { SeriesId = dto.SeriesId });
                unitOfWork.UserRepository.Update(user);
            }
        }

        unitOfWork.WantToFindRepository.Remove(item);
        await unitOfWork.CommitAsync(ct);
        return NoContent();
    }

    private async Task<WantToFindDto> GetDto(int id)
    {
        var items = await unitOfWork.WantToFindRepository.GetDtosAsync(UserId, HttpContext.RequestAborted);
        return items.Single(i => i.Id == id);
    }

    private static void Apply(AppUserWantToFind item, UpsertWantToFindDto dto)
    {
        item.Title = dto.Title.Trim();
        item.Authors = Clean(dto.Authors) ?? string.Empty;
        item.Summary = Clean(dto.Summary);
        item.Isbn = Clean(dto.Isbn);
        item.ExternalId = Clean(dto.ExternalId);
        item.CoverUrl = Clean(dto.CoverUrl);
        item.SourceUrl = Clean(dto.SourceUrl);
        item.Notes = Clean(dto.Notes);
    }

    private static string? Clean(string? value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static bool HasValidUrls(UpsertWantToFindDto dto)
    {
        return IsValidOptionalHttpUrl(dto.CoverUrl) && IsValidOptionalHttpUrl(dto.SourceUrl);
    }

    private static bool IsValidOptionalHttpUrl(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return true;
        return Uri.TryCreate(value, UriKind.Absolute, out var uri)
               && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps);
    }
}
