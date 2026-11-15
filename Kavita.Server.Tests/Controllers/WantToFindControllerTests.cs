using System.Threading.Tasks;
using Kavita.API.Store;
using Kavita.Database.Tests;
using Kavita.Models.Builders;
using Kavita.Models.DTOs.WantToFind;
using Kavita.Models.Entities.User;
using Kavita.Server.Controllers;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.DependencyInjection;
using NSubstitute;
using Xunit.Abstractions;

namespace Kavita.Server.Tests.Controllers;

public class WantToFindControllerTests(ITestOutputHelper outputHelper) : AbstractDbTest(outputHelper)
{
    [Fact]
    public async Task Resolve_RemovesMetadataItemAndOptionallyAddsSeriesToWantToRead()
    {
        var (unitOfWork, context, _) = await CreateDatabase();
        var library = new LibraryBuilder("Books")
            .WithSeries(new SeriesBuilder("Found Book").Build())
            .Build();
        var user = new AppUserBuilder("reader", "reader@example.com")
            .WithLibrary(library)
            .Build();
        user.WantToRead = [];
        context.AppUser.Add(user);
        await context.SaveChangesAsync();

        var item = new AppUserWantToFind { AppUserId = user.Id, Title = "Found Book" };
        context.AppUserWantToFind.Add(item);
        await context.SaveChangesAsync();

        var controller = CreateController(unitOfWork, user.Id);
        var result = await controller.Resolve(new ResolveWantToFindDto
        {
            WantToFindId = item.Id,
            SeriesId = library.Series.Single().Id,
            AddToWantToRead = true
        });

        Assert.IsType<NoContentResult>(result);
        Assert.Empty(context.AppUserWantToFind);
        Assert.Contains(context.Set<AppUserWantToRead>(), w => w.AppUserId == user.Id && w.SeriesId == library.Series.Single().Id);
    }

    [Fact]
    public async Task Resolve_CannotResolveAnotherUsersItem()
    {
        var (unitOfWork, context, _) = await CreateDatabase();
        var owner = new AppUserBuilder("owner", "owner@example.com").Build();
        var other = new AppUserBuilder("other", "other@example.com").Build();
        context.AppUser.AddRange(owner, other);
        await context.SaveChangesAsync();

        var item = new AppUserWantToFind { AppUserId = owner.Id, Title = "Private" };
        context.AppUserWantToFind.Add(item);
        await context.SaveChangesAsync();

        var result = await CreateController(unitOfWork, other.Id).Resolve(new ResolveWantToFindDto
        {
            WantToFindId = item.Id,
            SeriesId = 123,
            AddToWantToRead = false
        });

        Assert.IsType<NotFoundResult>(result);
        Assert.Single(context.AppUserWantToFind);
    }

    private static WantToFindController CreateController(Kavita.API.Database.IUnitOfWork unitOfWork, int userId)
    {
        var userContext = Substitute.For<IUserContext>();
        userContext.GetUserIdOrThrow().Returns(userId);
        var services = new ServiceCollection()
            .AddSingleton(userContext)
            .BuildServiceProvider();

        return new WantToFindController(unitOfWork)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = new DefaultHttpContext { RequestServices = services }
            }
        };
    }
}
